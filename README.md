# Schema Merger

Schema Merger, farklı CSV ve Excel tablolarındaki heterojen sütunları daha sonraki
aşamalarda kullanıcı onaylı bir planla tek bir **dikey (union/append)** çıktıda
birleştirecek açık kaynaklı, self-hosted bir Python aracıdır. Bu ilk sürüm yalnızca
dosyaları güvenli ve deterministik olarak profiller; birleştirme ya da LLM çağrısı
yapmaz.

Profiler her tablo için orijinal sütun adlarını, algılanan türleri, örnek değerleri,
benzersiz değer sayısını, boş oranını, uygun olduğunda min/max değerlerini ve biçim
ipuçlarını üretir. Türkçe ondalık biçimleri (`12,50`, `1.234,56`) ile ISO ve yaygın
Türkçe tarih biçimleri algılanır.

## Kurulum

```bash
python -m venv .venv
.venv\\Scripts\\activate  # Windows
pip install -e ".[dev]"
```

Bir CSV dosyasını profillemek için:

```bash
python -m cli.main profile --input tests/fixtures/sample_tr.csv
```

## Excel sheet davranışı

Çok sheet'li bir `.xlsx` dosyasında varsayılan olarak **tüm sheet'ler** taranır ve
her biri ayrı bir tablo profili olarak döner. Yalnızca bir sheet için
`--sheet <ad>` kullanın:

```bash
python -m cli.main profile --input tests/fixtures/sample_multi_sheet.xlsx --sheet Stok
```

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
kaç null oluştu).

**Review-guard:** `mapping.yaml` içinde hâlâ `review` durumunda bir eşleştirme
varsa `apply` **durur**, bekleyen sütunları listeler ve hiçbir çıktı yazmaz
(çıkış kodu `3`). Kör birleştirme yapılmaz.

`--format` verilmezse `schema.yaml` içindeki `output.format` kullanılır. Hedef şema
varsayılan olarak `mapping.yaml` klasöründeki `schema.yaml`'dır; kaynak dosyalar da
plandaki dosya adlarından aynı klasörde aranır. Farklı yerlerdeyse `--target-schema`
ve `--inputs` ile yol verin.

## Gizlilik ve API anahtarları

Kendi API anahtarınızı `.env` dosyanıza girin; anahtarlar **bize gitmez** ve hiçbir
zaman kaynak koda yazılmaz. `.env` dosyası `.gitignore` içinde ilk satırda
korunur. Bu aşama API anahtarı veya LLM kullanmaz.

## Mevcut kapsam

Proje uçtan uca çalışır: CSV/XLSX kaynaklarını profiller, incelemeye açık bir
`mapping.yaml` planı üretir ve onaylı planı `apply` ile `merged.xlsx|csv|sql` +
`merge_report.xlsx` çıktısına dönüştürür. Dönüştürme yalnızca dikey
(union/append) yapılır, TR/EN sayı ve tarih normalizasyonu uygulanır; satır
kaybedilmez, provenance sütunları her zaman eklenir ve dönüşüm hataları sayılır.

Entity resolution (ürün tekilleştirme) çekirdeği `core.entity` içinde hazırdır:
normalizasyon → blocking → embedding + iki eşik → yalnızca **gri bölge** için LLM
önerisi. Yüksek eşiğin üstü ve düşük eşiğin altı LLM'siz karara bağlanır; arada
kalan az sayıda çift LLM'e sorulur ve **her hâlde `review` kalır** — otomatik
birleşme yoktur. Embedding sağlayıcısı `EMBEDDING_PROVIDER` ile ayrı seçilir;
`ollama` seçilirse karşılaştırılan adlar makineden çıkmaz. Küme raporu ve küme
bazlı onay (4c) ile CLI'ya bağlanması henüz yapılmadı.

MVP yalnızca `.csv` ve `.xlsx` girdilerini destekler; canlı veritabanları ve SQL
dump'ları kapsam dışıdır. Hedef yalnızca dikey birleştirmedir, yatay join değildir.
