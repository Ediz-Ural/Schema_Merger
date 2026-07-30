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

## Gizlilik ve API anahtarları

Kendi API anahtarınızı `.env` dosyanıza girin; anahtarlar **bize gitmez** ve hiçbir
zaman kaynak koda yazılmaz. `.env` dosyası `.gitignore` içinde ilk satırda
korunur. Bu aşama API anahtarı veya LLM kullanmaz.

## Mevcut kapsam

Proje, CSV/XLSX kaynaklarını profilleyebilir, incelemeye açık bir `mapping.yaml`
planı üretebilir ve onaylı planları `core.transformer` ile yalnızca dikey
(union/append) olarak dönüştürebilir. Dönüştürme TR/EN sayı ve tarih
normalizasyonu uygular; satır kaybetmeden provenance bilgisi ile dönüşüm hata
sayaçlarını taşır.

MVP yalnızca `.csv` ve `.xlsx` girdilerini destekler; canlı veritabanları ve SQL
dump'ları kapsam dışıdır. Hedef yalnızca dikey birleştirmedir, yatay join değildir.
