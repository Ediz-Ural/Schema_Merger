# Codex Promptu — Aşama 2c: `analyze` CLI Komutu + Plan Üretimi

> **Kendi kendine yeter prompt.** Referans: `Project_Pdf/schema-merger-spec.pdf` v1.0.
> **Temiz Codex oturumunda çalıştır.** Önce §7 doğrulamasını yap.

## 0. Bağlam
Aşama 1 (Profiler), 2a (LLM + sözleşmeler), 2b (Matcher) tamam. Bu parça Faz 1'i uçtan uca
CLI'a bağlar: `analyze` komutu plan üretir, **hiçbir şeyi birleştirmez** (Belge Bölüm 5, 8).

## 1. Amaç
`merger analyze` komutunu tamamla: girdi dosyalarını profille → Matcher ile eşleştir →
`mapping.yaml` yaz → konsola özet bas. Faz 1 çıktısı tamamlanır.

## 2. Oluşturulacak / Değiştirilecek Dosyalar
```
cli/main.py           # "analyze" alt-komutu (Belge Bölüm 8 CLI imzası)
tests/test_cli_analyze.py
```
CLI imzası (Belge Bölüm 8):
```
merger analyze --inputs sales_2023.xlsx export_q4.csv \
               --target-schema schema.yaml \
               --out mapping.yaml
```

## 3. Gereksinimler
- `--inputs` (bir veya çok dosya), `--target-schema`, `--out`.
- Akış: Profiler(her dosya) → Matcher → `contracts` ile `mapping.yaml` yaz.
- Konsol özeti (Belge Bölüm 5 formatı):
  ```
  ✓ N sütun otomatik eşleşti
  ⚠ N sütun onay bekliyor (review)
  ✗ N sütun hiçbir dosyada bulunamadı
  → Planı düzenle: mapping.yaml, sonra: merger apply
  ```
- **Hiçbir birleştirme yapılmaz** — yalnızca plan. `apply` bu aşamada YOK (Aşama 3'te).
- Hata durumları anlamlı: dosya yok, şema bozuk, key yok → net mesaj.

## 4. Değişmez Kısıtlar (Belge Bölüm 14)
- İki fazlı akış: bu komut yalnızca **analyze** (plan). Birleştirme yok.
- Her eşleştirme confidence + status + gerekçe (mapping.yaml'da görünür).
- API key env'den; yoksa açık hata.
- LLM yalnızca sütun eşleştirmede; satır seviyesinde değil.

## 5. Testler
- [ ] `analyze` (FakeLLMClient ile) çalışıp geçerli `mapping.yaml` üretiyor.
- [ ] Konsol özeti auto/review/unmatched sayılarını doğru basıyor.
- [ ] Çok dosyalı girdi destekleniyor (`.xlsx` + `.csv` birlikte).
- [ ] Bozuk şema / eksik dosya → net hata, çökme yok.
- [ ] Üretilen mapping.yaml, `contracts` ile tekrar yüklenebiliyor (uçtan uca round-trip).

## 6. Kabul Kriterleri
1. [ ] `merger analyze --inputs ... --target-schema ... --out mapping.yaml` çalışır.
2. [ ] Geçerli, kullanıcı-düzenlenebilir `mapping.yaml` üretilir (Belge Bölüm 6 formatı).
3. [ ] Konsol özeti Belge Bölüm 5 formatında basar.
4. [ ] Birleştirme yapılmaz; `apply` yönlendirmesi mesajda var.
5. [ ] `pytest` yeşil, gerçek API çağrısı yok.

## 7. Önceki Aşama Doğrulama Kontrol Listesi (Aşama 2b)
- [ ] `core/matcher.py` profiller + şemadan mapping girdileri üretiyor mu?
- [ ] Her girdi confidence + status + reason taşıyor; belirsizler `review` mi?
- [ ] Dosya başına sabit LLM çağrısı (satır seviyesinde değil) mi?
- [ ] `pytest` yeşil mi, gerçek API çağrısı yok mu?

Eksik varsa önce gider, kısa rapor yaz, sonra 2c'ye başla.

## 8. Teslim
`analyze` komut çıktısı örneği, üretilen `mapping.yaml`, `pytest` çıktısı, kabul kriterleri ✓/✗.
> **Bu noktada Aşama 2 (Matcher + Plan Üretimi) tamamlanır:** `analyze` komutu + mapping.yaml üretimi çalışır.
