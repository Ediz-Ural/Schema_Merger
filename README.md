# Schema Merger

Schema Merger, farklı CSV ve Excel tablolarındaki heterojen sütunları kullanıcı
onaylı bir planla tek bir **dikey (union/append)** çıktıda birleştiren açık
kaynaklı, self-hosted bir Python aracıdır. LLM yalnızca plan üreten `analyze` ve
küme öneren `cluster` adımlarında kullanılır; `apply` tümüyle deterministiktir.

Profiler her tablo için orijinal sütun adlarını, algılanan türleri, örnek değerleri,
benzersiz değer sayısını, boş oranını, uygun olduğunda min/max değerlerini ve biçim
ipuçlarını üretir. Türkçe ondalık biçimleri (`12,50`, `1.234,56`) ile ISO ve yaygın
Türkçe tarih biçimleri algılanır.

## İçindekiler

- [Kurulum](#kurulum)
- [İki fazlı akış: `analyze` → onay → `apply`](#iki-fazlı-akış-analyze--onay--apply)
- [Semantik tuzak koruması](#semantik-tuzak-koruması)
- [Excel sheet davranışı](#excel-sheet-davranışı)
- [Validator: apply öncesi tutarlılık denetimi](#validator-apply-öncesi-tutarlılık-denetimi)
- [Entity resolution](#entity-resolution-cluster--küme-onayı--apply---clusters)
- [Veri sözleşmeleri](#veri-sözleşmeleri)
- [Kenar durumlar](#kenar-durumlar)
- [Web API (FastAPI backend)](#web-api-fastapi-backend)
- [Web arayüzü (React onay ekranı)](#web-arayüzü-react-onay-ekranı)
- [Gizlilik ve API anahtarları](#gizlilik-ve-api-anahtarları)
- [Testler](#testler)
- [Değişmez Kararlar Özeti](#değişmez-kararlar-özeti)
- [Mevcut kapsam](#mevcut-kapsam)
- [Lisans](#lisans)

## Kurulum

```bash
python -m venv .venv
.venv\\Scripts\\activate  # Windows
pip install -e ".[dev]"
pip install -e ".[openai]"   # analyze/cluster için sağlayıcı SDK'sı
                             # (Anthropic: ".[anthropic]"; Ollama'da gerekmez)
```

Ardından `.env.example`'ı `.env` olarak kopyalayıp anahtarınızı girin. `profile`
ve `apply` anahtar istemez.

Bir CSV dosyasını profillemek için:

```bash
python -m cli.main profile --input tests/fixtures/sample_tr.csv
```

Kurulumdan sonra aynı komutlar `merger profile`, `merger analyze`, `merger apply`
biçiminde de çalışır.

## İki fazlı akış: `analyze` → onay → `apply`

```bash
# Faz 1: analiz — plan üretir, hiçbir şeyi birleştirmez (LLM burada kullanılır)
python -m cli.main analyze --inputs sales_2023.csv export_q4.csv \
                           --target-schema schema.yaml \
                           --out mapping.yaml

# (kullanıcı mapping.yaml'daki review/unmatched satırlarını düzenler)

# Faz 2: uygula — deterministik, LLM yok
python -m cli.main apply --mapping mapping.yaml \
                         --out merged.xlsx --format xlsx
```

`apply` iki dosya üretir: `merged.<fmt>` (temiz birleşik veri, provenance sütunları
dâhil) ve yanına `merge_report.xlsx` (hangi sütun neye eşleşti, kaç satır geldi,
kaç null oluştu, validator ne buldu).

**Review-guard:** `mapping.yaml` içinde hâlâ `review` durumunda bir eşleştirme
varsa `apply` **durur**, bekleyen sütunları listeler ve hiçbir çıktı yazmaz
(çıkış kodu `3`). Kör birleştirme yapılmaz.

`--format` verilmezse `schema.yaml` içindeki `output.format` kullanılır. Hedef şema
varsayılan olarak `mapping.yaml` klasöründeki `schema.yaml`'dır; kaynak dosyalar da
plandaki dosya adlarından aynı klasörde aranır. Farklı yerlerdeyse `--target-schema`
ve `--inputs` ile yol verin.

Çıkış kodları: `0` başarılı, `2` girdi/yapılandırma hatası (dosya yok, şema bozuk,
API anahtarı yok, sağlayıcı isteği reddetti), `3` review-guard ya da validator
birleştirmeyi durdurdu. Sağlayıcı hataları (erişilmeyen model, geçersiz anahtar,
hız sınırı, ağ) ham traceback olarak değil, ne yapılacağını söyleyen tek satırlık
bir mesaj olarak düşer.

## Semantik tuzak koruması

Tip denetimi bazı hataları göremez: satır toplamı da birim fiyat gibi `decimal`'dır,
dolarlı fiyat da liralı fiyat gibi. Bu yüzden `analyze`, LLM önerdikten sonra
**deterministik bir ikinci göz** çalıştırır (`core/semantics.py`). Bu geçiş
yalnızca **güveni düşürür** — bir eşleştirmeyi asla onaylamaz, veriye dokunmaz:

- **Toplam ↔ birim.** Hedef birim başına bir değer beklerken kaynak sütun
  toplam/tutar/ara toplam/KDV gibi bir toplulaştırma ise (ya da tersi),
  eşleştirme `review`'a düşer. Örnek: `TUTAR` (2 × 10,00 = 20,00) → `unit_price`.
- **Para birimi çakışması.** Aynı hedef sütun farklı para birimlerinden
  besleniyorsa (`Birim Fiyat (TL)` ve `price_usd`, ya da örneklerdeki `₺`/`$`
  işaretleri) ilgili eşleştirmeler `review`'a düşer; dönüştürmeden birleştirmek
  değerleri karşılaştırılamaz kılar.

Aynı tuzaklar LLM'in sistem promptunda da yazılıdır, yani model çoğu zaman zaten
düşük güven verir; koruma vermediği durumlar için ağdır. `review` düşen satırı
onaylamak (`status: auto`), bırakmak (`unmatched`) ya da başka sütuna çevirmek
her zaman kullanıcının kararıdır.

## Excel sheet davranışı

Çok sheet'li bir `.xlsx` dosyasında varsayılan olarak **tüm sheet'ler** taranır.
`--sheet <ad>` her komutta aynı anlama gelir: yalnızca o sheet okunur. Bayrak
`.xlsx` kaynaklara uygulanır, CSV kaynaklar etkilenmez — karışık bir çalıştırmayı
bölmek gerekmez.

```bash
# tek sheet'i profille
python -m cli.main profile --input tests/fixtures/sample_multi_sheet.xlsx --sheet Stok

# planı yalnızca o sheet'e göre çıkar, sonra yine o sheet'i uygula
python -m cli.main analyze --inputs kitap.xlsx --target-schema schema.yaml \
                           --out mapping.yaml --sheet Satis
python -m cli.main apply --mapping mapping.yaml --out merged.csv --sheet Satis
```

`--sheet` verilmezse kurallar şunlardır:

- **`profile`**: her sheet ayrı bir tablo profili olarak listelenir.
- **`analyze`**: dosyanın tüm sheet'lerindeki sütunlar o dosyanın aday sütunları
  olarak değerlendirilir; plan yine dosya adıyla kaydedilir.
- **`apply` / `cluster`**: sheet'ler **dikey olarak alt alta eklenir**. O dosya için
  eşlenmiş kaynak sütunlardan **hiçbirini içermeyen** bir sheet (satış tablosunun
  yanındaki adres listesi gibi) boş satır üretmemek için **atlanır**; atlananlar
  komut çıktısında ve `merge_report.xlsx` → `Summary` → `skipped_sheets` satırında
  listelenir.
- Bir sheet birden fazlaysa provenance sütunu `_source_file` satırın geldiği
  sheet'i de yazar: `kitap.xlsx#Satis`. Tek sheet okunduğunda yalnızca dosya adı
  yazılır.
- Eşlenmiş bir kaynak sütun dosyanın **hiçbir** sheet'inde yoksa `apply` hata verir
  (çıkış kodu `2`); olmayan bir `--sheet` adı verilirse mevcut sheet adları
  listelenir.

## Validator: apply öncesi tutarlılık denetimi

`apply`, veriyi yazmadan önce **Matcher'ın kararını denetleyen ayrı bir gözden**
geçirir (LLM yok, tamamen deterministik). Dört denetim yapılır:

- **tip** — hedef tür ile birleşik sütunun türü uyuşuyor mu; dönüştürülemeyen
  değerlerin oranı yüksekse (varsayılan %20) muhtemelen yanlış sütun eşleşmiştir.
- **null** — bir kaynak dosyada **eşlenmiş** olduğu hâlde boş kalan sütun. Sütunun
  hiç eşlenmediği dosyalardan gelen boşluklar plan gereği olduğu için sayılmaz.
  Eşik `--null-threshold` ile değiştirilir (varsayılan `0.5`).
- **aykırı değer** — sayısal sütunlarda IQR×3 çiti, tarihlerde makul yıl aralığı.
- **required** — `required: true` hedef sütun eşlenmemişse ya da tek bir satırda
  bile boşsa hata.

Ciddi bulgular (`error`) ilgili eşleştirmeyi **`review`'a düşürür**: `apply` durur,
sorunlu satırları listeler ve **hiçbir çıktı yazmaz** (çıkış kodu `3`). Uyarılar
(`warning`) birleştirmeyi durdurmaz; `merge_report.xlsx` içindeki `Validation`
sayfasına ve özet sayaçlarına yazılır. Validator veriyi hiçbir koşulda sessizce
düzeltmez — yalnızca işaretler ve raporlar.

## Entity resolution: `cluster` → küme onayı → `apply --clusters`

Aynı ürünün farklı yazımlarını (`Coca Cola 330ml`, `Coca-Cola 33cl`,
`coca cola 0,33 lt`) tek ürüne indirmek isteğe bağlı bir adımdır ve onaylı bir
`mapping.yaml` gerektirir:

```bash
# Faz 1b: kümeleri öner — embedding + yalnızca gri bölge için LLM
python -m cli.main cluster --mapping mapping.yaml \
                           --column product_name \
                           --out clusters.yaml

# (kullanıcı clusters.yaml'ı düzenler: status auto/rejected, aday taşıma, bölme)

# Faz 2: uygula — LLM yok
python -m cli.main apply --mapping mapping.yaml --clusters clusters.yaml \
                         --out merged.xlsx --format xlsx
```

`cluster` yalnızca sütunun **farklı değerlerini** karşılaştırır (satır verisi
sağlayıcıya gitmez) ve `clusters.yaml` yazar; hiçbir şeyi birleştirmez. Dosyadaki
kurallar başlıkta yazılıdır:

- `status: auto` — küme onaylı; `apply` üyeleri canonical değere getirir.
- `status: review` — onaysız; **hiçbir üye birleştirilmez**, `merge_report`
  içindeki `Entity` sayfasında "belirsiz" olarak listelenir.
- `status: rejected` — kullanıcı farklı ürün dedi; birleştirilmez, belirsiz de
  sayılmaz.

Bir kümede belirsiz aday varsa küme `review` doğar: yüksek güvenli bağlar bile
onay beklemeden birleşmez. `apply` bu yüzden küme onayı için durmaz — onaysız
kümeler sadece uygulanmaz ve raporda görünür.

Tekilleştirme yalnızca **entity çözümünün kendi yarattığı** yinelenmeleri siler:
canonical değere getirildikten sonra tüm hedef sütunlarda aynılaşan ve farklı
yazımlardan gelen satırlar tek satıra iner. Aynı yazımın gerçekten iki kez geçtiği
satırlar (aynı ürünün iki ayrı satışı) korunur. Provenance bozulmaz: hayatta kalan
satır `_entity_cluster_id`, `<sütun>_original_value` ve `_merged_row_count`
sütunlarıyla birlikte birleştirdiği satırların tüm kaynak dosya/sütunlarını taşır.

## Veri sözleşmeleri

Üç YAML dosyası araç ile kullanıcı arasındaki sözleşmedir; hepsi
`core/contracts.py` tarafından doğrulanır ve kayıpsız round-trip eder. Bozuk bir
alan, satır numarasını ve beklenen değeri söyleyen bir hata verir.

### `schema.yaml` — hedef şema (kullanıcı yazar)

```yaml
target_columns:
  - name: product_name      # hedef sütun adı
    type: string            # string | integer | decimal | date | boolean
    required: true          # true ise boş/eksik bırakılamaz (validator zorlar)
  - name: unit_price
    type: decimal
    required: true
output:
  format: xlsx              # xlsx | csv | sql
  add_provenance: true      # provenance sütunları eklensin mi (önerilen: true)
```

### `mapping.yaml` — plan (analyze yazar, kullanıcı onaylar)

Her hedef sütun için **her kaynak dosyadan bir** eşleştirme satırı bulunur.

```yaml
- target_column: unit_price
  sources:
    - file: sales_2023.csv  # kaynak dosya adı (taşınabilir olsun diye yol değil)
      column: birim_fiyat   # kaynak sütun; eşleşme yoksa null
      confidence: 0.97      # 0..1
      status: auto          # auto | review | unmatched
      reason: "Tür ve örnek değerler uyuşuyor."   # kararın gerekçesi
```

- `auto` — onaylı; `apply` bu sütunu birleştirir.
- `review` — karar sizde; **tek bir `review` bile `apply`'ı durdurur**.
- `unmatched` — bilinçli olarak eşlenmedi; hedef sütun o dosyanın satırlarında
  boş kalır, satır atılmaz.

Onaylamak için `status`'u `auto` yapın (gerekirse `column`'u düzeltin); vazgeçmek
için `unmatched` yapıp `column: null` bırakın.

### `clusters.yaml` — entity kümeleri (cluster yazar, kullanıcı onaylar)

```yaml
- cluster_id: c001
  target_column: product_name
  canonical: Coca Cola 330ml     # members içindeki değerlerden biri olmalı
  status: review                 # auto | review | rejected
  members:
    - value: Coca Cola 330ml
      normalized: coca cola 330 ml
      row_count: 12
    - value: Coca-Cola 33cl
      normalized: coca cola 330 ml
      row_count: 3
  candidates:                    # onay bekleyen, henüz üye olmayan değerler
    - value: coca cola zero 330ml
      similarity: 0.86
      suggestion: undecided      # same | different | undecided
      source: llm                # embedding | llm
      confidence: 0.6
      reason: "Şeker içeriği farklı olabilir."
  reason: "Gri bölgede bir aday var."
```

Bir adayı kabul etmek için `candidates`'tan `members`'a taşıyın; kümeyi bölmek için
üyeyi listeden çıkarıp yeni bir `cluster_id` ile ayrı küme yazın. Bir değer yalnızca
tek bir kümenin üyesi olabilir.

### Provenance sütunları

`add_provenance: true` iken çıktıya eklenen sütunlar:

| Sütun | Anlamı |
| --- | --- |
| `_source_file` | Satırın geldiği dosya (çok sheet'te `dosya.xlsx#Sheet`) |
| `<hedef>_source_column` | O hedef sütunun bu satırdaki kaynak sütun adı |
| `_entity_cluster_id` | Satırın uygulandığı onaylı küme (entity resolution) |
| `<hedef>_original_value` | Canonical'e getirilmeden önceki yazım |
| `_merged_row_count` | Bu satırın temsil ettiği kaynak satır sayısı |

## Kenar durumlar

**Çakışan değerler.** İki dosya aynı ürün için farklı fiyat söylüyorsa **iki satır
da korunur**; hangisinin "doğru" olduğu **otomatik seçilmez** (kapsam dışı). Fark
provenance ile izlenir: `_source_file` ve `<hedef>_source_column` her satırda hangi
dosyanın hangi sütunundan geldiğini yazar, `merge_report.xlsx` → `Columns` sayfası
sütun bazında aynı bilgiyi verir. Hangisini tutacağınıza siz karar verirsiniz.

**Tip çatışmaları.** Değerler hedef türe TR/EN normalizasyonuyla çevrilir
(`12,50` ve `12.50` → `12.5`; `31.12.2024`, `31/12/2024`, `2024-12-31` → tarih).
Çevrilemeyen bir değer **sessizce silinmez**: hücre null olur, satır kalır, hata
`merge_report` → `Summary.total_conversion_errors` ve `Columns.conversion_errors`
sayaçlarına yazılır ve komut çıktısında görünür. Oran validator eşiğini aşarsa
(varsayılan %20) muhtemelen yanlış sütun eşleşmiştir: eşleştirme `review`'a düşer
ve `apply` durur.

**API anahtarı yok.** `analyze` ve `cluster` bir sağlayıcı ister. Anahtar yoksa
komut hiçbir dosya yazmadan durur ve eksik değişkeni adıyla söyler:

```
$ python -m cli.main analyze --inputs sales.csv --target-schema schema.yaml --out mapping.yaml
Error: OPENAI_API_KEY tanımlı değil, .env dosyanı kontrol et.
```

(`LLM_PROVIDER=anthropic` ise `ANTHROPIC_API_KEY`; `ollama` yerel çalıştığı için
anahtar istemez.) `profile` ve `apply` hiçbir koşulda anahtar istemez — Faz 2
tamamen deterministiktir.

**Boş / bulunamayan girdi.** Olmayan dosya, desteklenmeyen uzantı (`.csv` ve
`.xlsx` dışı), eksik hedef şema ve mapping'de adı geçip diskte olmayan kaynak,
çıkış kodu `2` ile ve ne yapılacağını söyleyen bir mesajla bildirilir.

## Web API (FastAPI backend)

Web arayüzü ile CLI **aynı çekirdeği** kullanır: `web/backend` yalnızca sunum ve
orkestrasyon katmanıdır, hiçbir iş mantığını ikinci kez yazmaz. Değişmez
kararların hepsi API seviyesinde de geçerlidir — özellikle review-guard: planda
`review` kalırsa `apply` **409** ile reddedilir ve hiçbir dosya yazılmaz.

```bash
pip install -e ".[web]"
uvicorn web.backend.main:app --reload
# Etkileşimli dokümantasyon: http://127.0.0.1:8000/docs
```

Her oturum bir klasördür: yüklenen kaynaklar, `schema.yaml`, `mapping.yaml`,
`clusters.yaml` ve çıktılar aynı çalışma klasörüne yazılır; aynı klasörde
`merger` komutlarıyla devam edilebilir. Klasörlerin kökü `SCHEMA_MERGER_WEB_ROOT`
ile seçilir (tanımsızsa geçici bir klasör kullanılır); tarayıcı kaynakları
`SCHEMA_MERGER_CORS_ORIGINS` ile ayarlanır (öntanımlı: `http://localhost:5173`).

| Yöntem | Yol | Ne yapar |
|--------|-----|----------|
| `POST` | `/upload` | Kaynak dosyalar + `schema.yaml` yükler, oturum açar (`201`). |
| `POST` | `/analyze/{session_id}` | Faz 1: profil + LLM eşleştirme → plan döndürür. |
| `GET` | `/mapping/{session_id}` | Planı (auto/review/unmatched sayılarıyla) getirir. |
| `GET` | `/columns/{session_id}` | Kaynak dosyalardaki gerçek sütunlar (düzeltme dropdown'ı için). |
| `PUT` | `/mapping/{session_id}` | Kullanıcının onayladığı planı yazar. |
| `POST` | `/cluster/{session_id}` | Faz 1b: bir sütun için entity kümeleri önerir. |
| `GET` / `PUT` | `/clusters/{session_id}` | Küme önerilerini getirir / onayları yazar. |
| `POST` | `/apply/{session_id}` | Faz 2: LLM'siz birleştirme; review varsa `409`. |
| `GET` | `/download/{session_id}/{merged\|report}` | `merged.<fmt>` ve `merge_report.xlsx`. |
| `GET` | `/status/{session_id}` | Oturumun hangi adımda olduğu (basit ilerleme). |
| `DELETE` | `/session/{session_id}` | Oturumu ve dosyalarını siler. |
| `GET` | `/provider` | Yapılandırılmış sağlayıcı ve model — **anahtar dönmez**. |
| `GET` | `/health` | Ayakta mı? |

Durum kodları: `400` bozuk şema/plan/istek, `404` bilinmeyen oturum ya da henüz
üretilmemiş çıktı, `409` review-guard veya validator'ın durdurduğu `apply`,
`502` sağlayıcı isteği reddetti ya da başarısız oldu
(`{"error": "llm_request_failed"}`), `503` sağlayıcı anahtarı yapılandırılmamış
(`{"error": "llm_not_configured"}`).
`409` gövdesi hangi eşleştirmelerin ya da bulguların engellediğini ve
`written: false` bilgisini taşır.

**Anahtar güvenliği:** sağlayıcı anahtarı yalnızca sunucunun ortam
değişkenlerinden (`.env`) okunur; istekle alınmaz, oturum klasörüne yazılmaz ve
hiçbir yanıtta geri dönmez. `/provider` yalnızca sağlayıcı adını ve anahtarın
tanımlı olup olmadığını bildirir. Anahtar ileride tarayıcıdan alınacaksa
yalnızca süreç belleğinde/oturum bazlı tutulmalı, diske **yazılmamalıdır**.

## Web arayüzü (React onay ekranı)

Teknik olmayan kullanıcı için görsel onay ekranı `web/frontend/` altındadır
(React + TypeScript + Vite). İş mantığı içermez: her adım yukarıdaki HTTP API
üzerinden aynı çekirdeğe gider.

```bash
uvicorn web.backend.main:app --reload    # 1. terminal (proje kökü)
cd web/frontend && npm install && npm run dev   # 2. terminal → http://localhost:5173
```

Akış ekranda da iki fazlıdır: **yükle → analiz → plan onayı → birleştir → indir**.
Plan kart olarak gösterilir — `auto` **yeşil**, `review` **sarı**, `unmatched`
**kırmızı** — ve her kartta hedef sütun, kaynak dosya, güven, gerekçe ve örnek
değerler bulunur. Düzeltme dropdown iledir; seçenekler `GET /columns`'un
bildirdiği, o dosyada gerçekten var olan sütunlardır, `(boş bırak)` ise sütunu
bilinçli olarak eşlememek demektir.

**"Birleştir" butonu yalnızca hiç `review` kalmadığında aktiftir.** Aynı kural
backend'de `409` ile de uygulanır; o yanıt gelirse ekran engelleyen
eşleştirmeleri ve "hiçbir dosya yazılmadı" bilgisini gösterir. API anahtarı
tarayıcıya hiç gelmez: `/provider` yalnızca sağlayıcı adını ve anahtarın
yapılandırılmış olup olmadığını bildirir. Ayrıntı ve dağıtım seçenekleri için
[`web/frontend/README.md`](web/frontend/README.md).

## Gizlilik ve API anahtarları

Kendi API anahtarınızı `.env` dosyanıza girin; anahtarlar **bize gitmez** ve hiçbir
zaman kaynak koda yazılmaz. `.env` dosyası `.gitignore` içinde ilk satırda
korunur. `profile` ve `apply` komutları API anahtarı istemez; anahtar yalnızca
`analyze` ve `cluster` için gerekir.

Katkı verirken commit öncesi bir sızıntı taraması önerilir — örneğin
[`gitleaks`](https://github.com/gitleaks/gitleaks) ya da `git-secrets`'i bir
`pre-commit` kancasına bağlayın; `.env` zaten yok sayılıyor olsa da yanlışlıkla
yapıştırılmış bir anahtarı yakalar.

## Testler

```bash
pytest                                   # çekirdek + CLI + web backend (ağa çıkmaz)
cd web/frontend && npm test              # React onay ekranı (vitest)

SCHEMA_MERGER_LIVE=1 pytest -m live      # gerçek sağlayıcıya isabet testleri (ücretli)
```

Testler ağa çıkmaz: LLM ve embedding sağlayıcıları `FakeLLMClient` /
`FakeEmbeddingClient` ile enjekte edilir, `apply` tarafında ise bir istemcinin
kurulmadığı ayrıca test edilir. Frontend testlerinde de backend mock'lanır;
kart renkleri, review varken pasif kalan "Birleştir" butonu ve düzeltmenin
`PUT /mapping` çağrısına dönüşmesi doğrulanır.

`tests/live/` altındaki **isabet testleri** ayrı durur: varsayılan koşuda hariç
tutulurlar, `SCHEMA_MERGER_LIVE=1 pytest -m live` ile yapılandırılmış gerçek
sağlayıcıya gider ve modelin doğru sütunu seçtiğini ölçerler — diller/kısaltmalar
arası eşleşme, olmayan sütunun uydurulmaması, toplam sütununun birim fiyata
onaysız girmemesi, iki para biriminin sessizce birleşmemesi ve gerçek
embedding'lerle ürün kümeleme.

## Değişmez Kararlar Özeti

Belge Bölüm 14'teki kararlar; hepsi kodda ve testlerde korunur:

1. **Yalnızca dikey birleştirme** (union/append). Yatay join kapsam dışıdır.
2. **`analyze` → kullanıcı onayı → `apply`** iki fazlı akış; tek adımda birleştirme yok.
3. **LLM satır verisini işlemez.** LLM'e yalnızca sütun profilleri (ad, tür, örnek
   değerler) ve entity adımında sütunun farklı değerleri gider.
4. Her eşleştirme **confidence + status + gerekçe** taşır.
5. Planda çözülmemiş **`review` kalırsa `apply` durur** ve hiçbir çıktı yazmaz.
6. **Provenance her zaman** yazılır: hangi satır hangi dosya ve sütundan geldi.
7. **API anahtarı asla repoya girmez**; `.env` ile verilir, `.gitignore`'dadır.
8. Önce **çekirdek + CLI**; UI daha sonra **aynı çekirdeği** kullanır.

## Mevcut kapsam

Proje uçtan uca çalışır: CSV/XLSX kaynaklarını profiller, incelemeye açık bir
`mapping.yaml` planı üretir ve onaylı planı `apply` ile `merged.xlsx|csv|sql` +
`merge_report.xlsx` çıktısına dönüştürür. Dönüştürme yalnızca dikey
(union/append) yapılır, TR/EN sayı ve tarih normalizasyonu uygulanır; satır
kaybedilmez, provenance sütunları her zaman eklenir ve dönüşüm hataları sayılır.
Yazmadan önce validator tip/null/format/aykırı değer denetimi yapar; ciddi
bulgular eşleştirmeyi `review`'a döndürür ve birleştirmeyi durdurur. Plan
üretilirken ayrıca semantik tuzak koruması çalışır: toplam/birim karışması ve
para birimi çakışması, model ne kadar emin olursa olsun `review`'a düşer.

Entity resolution (ürün tekilleştirme) uçtan uca bağlıdır: normalizasyon →
blocking → embedding + iki eşik → yalnızca **gri bölge** için LLM önerisi →
küme raporu → küme bazlı onay → tekilleştirme. Yüksek eşiğin üstü ve düşük eşiğin
altı LLM'siz karara bağlanır; arada kalan az sayıda çift LLM'e sorulur ve **her
hâlde `review` kalır** — otomatik birleşme yoktur. Embedding sağlayıcısı
`EMBEDDING_PROVIDER` ile ayrı seçilir; `ollama` seçilirse karşılaştırılan adlar
makineden çıkmaz.

Web arayüzü uçtan uca hazırdır: FastAPI backend (Aşama 6a) çekirdeği saran ince
bir katman olarak analyze/mapping/cluster/apply/download akışını HTTP üzerinden
sunar, React onay ekranı (Aşama 6b) ise planı yeşil/sarı/kırmızı kartlarla
gösterip dropdown ile düzeltmeye açar. Review-guard her iki katmanda da
korunur: buton review varken pasiftir, API aynı durumda `409` döner.
Entity resolution şimdilik yalnızca CLI ve API üzerinden yapılır; onaylı
kümeleri `apply` her iki arayüzde de uygular.

MVP yalnızca `.csv` ve `.xlsx` girdilerini destekler; canlı veritabanları ve SQL
dump'ları kapsam dışıdır. Hedef yalnızca dikey birleştirmedir, yatay join değildir.

## Lisans

MIT — bkz. [LICENSE](LICENSE).
