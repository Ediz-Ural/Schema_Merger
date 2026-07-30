# Codex Promptu — Aşama 1: İskelet + Veri Katmanı (Profiler)

> **Bu prompt kendi kendine yeter.** Referans kaynak `Project_Pdf/schema-merger-spec.pdf`
> (Schema Merger Proje Spesifikasyonu v1.0). Aşağıdaki tüm kararlar o belgeden gelir;
> belgeyle çelişen hiçbir şey yapma.

---

## 0. Rolün ve Bağlam

Sen `schema-merger` projesini sıfırdan kuran bir kod ajanısın. Bu proje, farklı
Excel/CSV dosyalarındaki heterojen tabloları, kullanıcı onaylı bir eşleştirme planı
üzerinden **tek bir dikey (union/append) birleşik dosyaya** dönüştüren, açık kaynak
(MIT, self-hosted) bir Python aracıdır. Sistem iki fazlıdır: `analyze` (LLM ile plan
üretir) → kullanıcı onayı → `apply` (LLM yok, deterministik uygular).

**Bu aşamada LLM YOK.** Sadece proje iskeleti + güvenlik + Profiler yazacaksın.

---

## 1. Aşamanın Amacı

Yol Haritası **Aşama 1 — İskelet + Veri Katmanı**:
Proje yapısını kur, `.gitignore`/`.env` güvenliğini baştan doğru koy, ve **Profiler**
bileşenini yaz (dosya okuma + profilleme). Saf pandas/polars, LLM yok. TR/EN tip
normalizasyonu için temel baştan konur.

**Aşama çıktısı:** Çalışan bir profiler + güvenli repo iskeleti.

Belgedeki ilgili kararlara referans:
- **Bölüm 2 (Kapsam):** Girdi formatı yalnızca `.xlsx`, `.csv`. Canlı SQL / `.sql` dump kapsam dışı.
- **Bölüm 4 (Eşleştirme sinyalleri):** Profiler dört sinyali hazırlar — sütun ismi, veri tipi, örnek değerler (ilk N satır), istatistiksel profil (unique count, null oranı, min/max, format pattern).
- **Bölüm 7 (Profiler):** LLM YOK · pandas/polars. Her girdi dosyasını tarar; çok-sheet'li Excel'de sheet seçimini yönetir.
- **Bölüm 8 (Proje Yapısı):** Aşağıdaki dizin ağacı zorunludur.
- **Bölüm 9 (Güvenlik):** API key asla repoya girmez.
- **Bölüm 11 (Kenar durumlar):** TR/EN sayı-tarih normalizasyonu olmazsa olmaz; çok-sheet'li Excel davranışı kararlaştırılıp dokümante edilir.

---

## 2. Oluşturulacak / Değiştirilecek Dosyalar (tam liste)

```
schema-merger/
├── .env.example            # boş key şablonu (repoda VAR) — OPENAI_API_KEY=, ANTHROPIC_API_KEY=
├── .gitignore              # .env İLK SATIR olacak
├── LICENSE                 # MIT
├── README.md               # ne yapar + kurulum + "kendi key'inizi girin, bize gitmez" uyarısı
├── pyproject.toml          # paket metadata + bağımlılıklar (pandas/polars, openpyxl, python-dotenv)
├── core/
│   ├── __init__.py
│   ├── profiler.py         # BU AŞAMANIN ANA İŞİ: dosya → sütun metadata, tip, örnek, istatistik
│   └── types.py            # ColumnProfile, FileProfile gibi veri sınıfları (dataclass)
├── cli/
│   ├── __init__.py
│   └── main.py             # "profile" alt-komutu (analyze/apply sonraki aşamalarda gelecek — iskeleti bırak)
└── tests/
    ├── __init__.py
    ├── fixtures/           # küçük örnek .xlsx ve .csv (TR sayı formatı içeren)
    └── test_profiler.py
```

> **Not:** `matcher.py`, `entity.py`, `validator.py`, `transformer.py`, `writer.py`,
> `llm.py` bu aşamada YAZILMAZ (sonraki aşamalar). İstersen boş `# TODO: Aşama N`
> placeholder bırakabilirsin ama zorunlu değil.

---

## 3. Bileşen Gereksinimleri — Profiler

`core/profiler.py`, bir girdi dosyasını (`.xlsx` veya `.csv`) alıp her sütun için
aşağıdakileri üreten deterministik kod olmalı:

1. **Sütun ismi** (orijinal haliyle korunur — provenance için gerekli).
2. **Veri tipi:** `string | integer | decimal | date | boolean` (pandas/polars dtype'tan çıkar; TR formatları için normalizasyon dene).
3. **Örnek değerler:** ilk N (varsayılan 5–10) non-null değer.
4. **İstatistiksel profil:** `unique_count`, `null_ratio`, `min`, `max` (sayısal/tarih sütunlar için), tespit edilen `format_pattern` (ör. TR "12,50", ISO tarih).

**Çok-sheet'li Excel kararı (dokümante et):** Varsayılan olarak tüm sheet'ler taranır ve
her sheet ayrı bir "tablo" olarak profillenir; kullanıcı `--sheet <ad>` ile tek sheet
seçebilir. Bu davranışı README'ye ve fonksiyon docstring'ine yaz.

**TR/EN tip normalizasyonu (temel):** Bir sütunun sayısal olup olmadığını tespit ederken
Türkçe biçimi (`"12,50"`, binlik `"1.234,56"`) de decimal olarak tanıyabilmeli. Tarih için
en azından yaygın TR (`gg.aa.yyyy`) ve ISO formatlarını tanı. Bu aşamada mükemmellik
gerekmez ama altyapı kurulmalı (ör. `core/normalize.py`'a taşınabilir veya profiler içinde
yardımcı fonksiyon).

**CLI:** `python -m cli.main profile --input <dosya> [--sheet <ad>]` çalıştırıldığında
konsola okunabilir bir profil özeti bassın (sütun başına: isim, tip, null oranı, örnekler).

---

## 4. Değişmez Kısıtların Hatırlatması (Bölüm 14 — hiçbir aşamada ihlal edilmez)

- **LLM veriyi elle işlemez.** (Bu aşamada zaten LLM yok — ama Profiler asla satır verisini "düzeltmeye" kalkmaz, sadece profiller.)
- **API key asla repoya girmez.** `.env` `.gitignore`'ın ilk satırı; repoda yalnızca `.env.example` (boş) bulunur; kod key'i ortam değişkeninden okur, asla hardcode etmez. Key yoksa açık hata mesajı verir. (Bu aşamada key kullanılmıyor ama iskelet güvenli kurulmalı.)
- **Sadece dikey (union) birleştirme** hedefleniyor — profiler bunu bilmek zorunda değil ama kapsamı genişletme.
- **LLM satır seviyesinde çalışmaz.**

---

## 5. Bu Aşamada Yazılması Gereken Testler

`tests/test_profiler.py` içinde en az:

- [ ] `.csv` dosyası okunup her sütun için `ColumnProfile` üretiliyor.
- [ ] `.xlsx` dosyası okunuyor; çok-sheet'li dosyada tüm sheet'ler profilleniyor, `--sheet` ile tek sheet seçilebiliyor.
- [ ] Veri tipi tespiti doğru: integer / decimal / string / date ayrımı.
- [ ] **TR sayı formatı** (`"12,50"`, `"1.234,56"`) decimal olarak tanınıyor (regresyon testi).
- [ ] `null_ratio` ve `unique_count` doğru hesaplanıyor (bilinen fixture ile).
- [ ] Desteklenmeyen format / bozuk dosya için anlamlı hata veriliyor.

Testler `pytest` ile geçmeli. `tests/fixtures/` altına küçük, deterministik örnek
dosyalar koy (TR formatı içeren en az bir tane).

---

## 6. Kabul Kriterleri (aşama "tamamlandı" sayılması için)

Aşağıdakilerin **hepsi** somut olarak doğrulanabilir olmalı:

1. [ ] Bölüm 2'deki dizin ağacı birebir mevcut (`core/`, `cli/`, `tests/` ve belirtilen dosyalar).
2. [ ] `.gitignore`'ın **ilk satırı** `.env`; repoda `.env` yok, `.env.example` (boş anahtarlarla) var.
3. [ ] `LICENSE` MIT; `README.md` "ne yapar + kurulum + kendi key'inizi girin, bize gitmez" notunu içeriyor.
4. [ ] `pip install -e .` (veya eşdeğeri) sorunsuz kuruluyor; bağımlılıklar `pyproject.toml`'da tanımlı.
5. [ ] `python -m cli.main profile --input tests/fixtures/<ornek>.csv` çalışıyor ve okunabilir profil özeti basıyor.
6. [ ] Çok-sheet'li Excel davranışı README'de dokümante edilmiş.
7. [ ] `pytest` çalışıyor ve tüm testler geçiyor (TR sayı formatı testi dahil).
8. [ ] Kodda hiçbir yerde hardcode API key yok; LLM çağrısı yok.

---

## 7. Önceki Aşama Doğrulama Kontrol Listesi

> **Bu format her aşama promptunda bulunur.** Yeni bir oturuma başladığında, yeni aşamaya
> geçmeden önce önceki aşamanın gerçekten tamamlandığını doğrula: kabul kriterlerini tek tek
> kontrol et (dosyalar var mı, testler geçiyor mu, komut çalışıyor mu), eksik varsa önce onu
> gider, sonra kısa bir raporla (neyin tamam / neyin eksik) özetle.

**Aşama 1 için önceki aşama YOKTUR** — bu ilk aşamadır, doğrulama boş geçilebilir.

Yine de formatı göstermek için, bir sonraki aşama (Aşama 2 — Matcher) başlarken şu
kontroller yapılacaktır:

- [ ] Dizin ağacı (Bölüm 2) mevcut mu?
- [ ] `.gitignore` ilk satırı `.env` mi, `.env.example` var mı, `.env` repoda YOK mu?
- [ ] `python -m cli.main profile --input <fixture>` çalışıyor ve profil basıyor mu?
- [ ] `pytest` yeşil mi (TR sayı formatı testi dahil)?
- [ ] Kodda hardcode key / gereksiz LLM çağrısı var mı? (olmamalı)

Eksik bulunursa: önce giderilir, ardından kısa doğrulama raporu yazılır, sonra Aşama 2'ye geçilir.

---

## 8. Çıktı / Teslim

Bittiğinde şunu raporla:
- Oluşturulan dosyaların listesi.
- `pytest` çıktısı (tüm testler geçti mi).
- Örnek `profile` komutu çıktısı.
- Kabul kriterlerinin madde madde durumu (✓ / ✗).
