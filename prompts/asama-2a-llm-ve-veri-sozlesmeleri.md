# Codex Promptu — Aşama 2a: LLM Soyutlama Katmanı + Veri Sözleşmeleri

> **Kendi kendine yeter prompt.** Referans kaynak: `Project_Pdf/schema-merger-spec.pdf`
> (Schema Merger Spesifikasyonu v1.0). Belge ile çelişme.
> **Temiz Codex oturumunda çalıştır.** Önce §7'deki önceki-aşama doğrulamasını yap.

## 0. Bağlam
`schema-merger`: heterojen Excel/CSV tablolarını, kullanıcı onaylı bir plan üzerinden
tek bir **dikey (union)** birleşik dosyaya dönüştüren açık kaynak Python aracı. İki fazlı:
`analyze` (LLM ile plan üretir) → kullanıcı onayı → `apply` (LLM yok). Aşama 1'de repo
iskeleti + Profiler kuruldu. Şimdi Aşama 2'nin ilk parçası.

## 1. Amaç
Matcher'ın ihtiyaç duyacağı iki temeli kur:
- **LLM soyutlama katmanı** (`core/llm.py`): key yönetimi + model soyutlaması. OpenAI /
  Anthropic / Ollama (local) provider'ları config'den seçilebilir (Belge Bölüm 7 "LLM Katmanı").
- **Veri sözleşmeleri** (`core/contracts.py`): `schema.yaml` (hedef şema) ve `mapping.yaml`
  (Faz 1 çıktısı) için yükleme/doğrulama/yazma modelleri (Belge Bölüm 6).

Bu parçada **eşleştirme mantığı YOK** (o 2b'de). Sadece sağlam altyapı.

## 2. Oluşturulacak / Değiştirilecek Dosyalar
```
core/llm.py           # provider soyutlama: complete(prompt) -> str; key .env'den; provider config'den
core/contracts.py     # schema.yaml & mapping.yaml load/validate/dump (dataclass/pydantic)
core/types.py         # (Aşama 1'den) gerekiyorsa TargetColumn, SourceMatch, MappingEntry ekle
.env.example          # OPENAI_API_KEY= ANTHROPIC_API_KEY= (varsa) LLM_PROVIDER=
tests/test_llm.py
tests/test_contracts.py
tests/fixtures/schema.yaml   # Belge Bölüm 6'daki örneğe uygun
```

## 3. Gereksinimler
**`core/llm.py`:**
- Ortak arayüz: `class LLMClient` → `complete(system, user) -> str` (ve/veya JSON döndüren yardımcı).
- Provider seçimi config/`.env` üzerinden: `openai | anthropic | ollama`.
- Key **yalnızca ortam değişkeninden** (`python-dotenv`), asla hardcode yok. Key yoksa
  **açık hata**: örn. `"OPENAI_API_KEY tanımlı değil, .env dosyanı kontrol et."`
- Ağ çağrısı test edilebilir olsun: gerçek API'yi test'te çağırma; `FakeLLMClient` /
  enjekte edilebilir client ile mock'la.

**`core/contracts.py`:**
- `schema.yaml` yükle → `target_columns` (name/type/required) + `output` (format, add_provenance).
- `mapping.yaml` modeli: her `target_column` için `sources[]` = {file, column, confidence,
  status ∈ {auto,review,unmatched}, reason, samples?}. Load + dump (round-trip korunur).
- Şema/mapping doğrulama: geçersiz `status`, eksik zorunlu alan → anlamlı hata.

## 4. Değişmez Kısıtlar (Belge Bölüm 14)
- API key asla repoya girmez; kod key'i env'den okur, açık hata verir.
- LLM asla satır verisi işlemez (bu katman yalnızca metin tamamlama sağlar; veri satırı geçmez).
- `status` yalnızca `auto | review | unmatched` olabilir.

## 5. Testler
- [ ] `LLM_PROVIDER` seçimine göre doğru client kuruluyor; key yoksa açık hata.
- [ ] Gerçek ağ çağrısı yapılmıyor (mock/fake ile).
- [ ] `schema.yaml` (fixture) doğru parse ediliyor; `output.format` ∈ {xlsx,csv,sql}.
- [ ] `mapping.yaml` round-trip: yükle → yaz → tekrar yükle, kayıpsız.
- [ ] Geçersiz `status` reddediliyor.

## 6. Kabul Kriterleri
1. [ ] `core/llm.py` çalışır; key env'den okunur, yoksa açık hata; test'te gerçek çağrı yok.
2. [ ] `core/contracts.py` schema.yaml + mapping.yaml load/validate/dump yapar (round-trip testli).
3. [ ] `.env.example` provider + key alanlarını içerir; `.env` repoda yok.
4. [ ] `pytest` yeşil.
5. [ ] Hiçbir yerde hardcode key yok.

## 7. Önceki Aşama Doğrulama Kontrol Listesi (Aşama 1)
Yeni aşamaya geçmeden önce doğrula; eksik varsa önce gider, sonra kısa rapor yaz:
- [ ] Dizin ağacı (Belge Bölüm 8) mevcut mu? (`core/`, `cli/`, `tests/`)
- [ ] `.gitignore` ilk satırı `.env` mi; `.env.example` var, `.env` repoda YOK mu?
- [ ] `python -m cli.main profile --input <fixture>` çalışıp profil basıyor mu?
- [ ] `pytest` yeşil mi (TR sayı formatı testi dahil)?
- [ ] Kodda hardcode key / gereksiz LLM çağrısı yok mu?

Sonuç: neyin tamam / neyin eksik olduğunu kısa raporla, sonra 2a'ya başla.

## 8. Teslim
Oluşturulan dosyalar, `pytest` çıktısı, kabul kriterlerinin ✓/✗ durumu.
