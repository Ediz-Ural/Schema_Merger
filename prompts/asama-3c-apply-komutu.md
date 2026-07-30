# Codex Promptu — Aşama 3c: `apply` CLI + Review-Guard → Uçtan Uca MVP

> **Kendi kendine yeter prompt.** Referans: `Project_Pdf/schema-merger-spec.pdf` v1.0.
> **Temiz Codex oturumunda çalıştır.** Önce §7 doğrulamasını yap.

## 0. Bağlam
Transformer (3a) ve Writer (3b) hazır. Bu parça `apply` komutunu bağlar ve **kör
birleştirmeyi engelleyen review-guard'ı** ekler. Bittiğinde **uçtan uca çalışan MVP** olur
(entity resolution olmadan bile kullanılabilir — Belge Bölüm 12, Aşama 3).

## 1. Amaç
`merger apply` komutunu tamamla: onaylı `mapping.yaml` → Validator (temel) → Transformer →
Writer. **LLM YOK.** İki koruma zorunlu (Belge Bölüm 5).

## 2. Oluşturulacak / Değiştirilecek Dosyalar
```
cli/main.py           # "apply" alt-komutu (Belge Bölüm 8 imzası)
tests/test_cli_apply.py
tests/test_e2e.py     # analyze -> (mapping düzenle) -> apply uçtan uca akış
```
CLI imzası (Belge Bölüm 8):
```
merger apply --mapping mapping.yaml \
             --out merged.xlsx --format xlsx
```

## 3. Gereksinimler
- `--mapping`, `--out`, `--format` (xlsx|csv|sql).
- **Koruma 1 (review-guard):** `mapping.yaml`'da hâlâ `review` durumunda satır varsa
  **apply DURUR** ve net uyarır — hangi sütunların beklediğini listeler. Kör birleştirme yok.
- **Koruma 2:** Provenance sütunları eklenir (Writer üzerinden).
- Çıktı iki dosya: `merged.<fmt>` + `merge_report.xlsx`.
- **LLM kullanılmaz** — bu komut deterministik. (Config'de LLM olsa bile çağrılmaz.)
- Konsolda kısa özet: kaç satır yazıldı, kaç null, rapor nerede.

## 4. Değişmez Kısıtlar (Belge Bölüm 14)
- `apply`, `review` kalırsa **durur** — kör birleştirme yok.
- Faz 2'de **LLM YOK**.
- Provenance her zaman eklenir.
- Sadece dikey birleştirme.

## 5. Testler
- [ ] Tüm eşleşmeler `auto` → apply başarılı, `merged` + `merge_report` üretilir.
- [ ] En az bir `review` varsa → apply **durur**, net uyarı, çıktı yazılmaz.
- [ ] `unmatched` sütun → hedef null, satır kaybı yok, apply çalışır.
- [ ] Format seçimi (xlsx/csv/sql) doğru çıktı üretir.
- [ ] **E2E:** `analyze` (FakeLLM) → mapping'i tüm `auto` yap → `apply` → beklenen birleşik dosya.

## 6. Kabul Kriterleri
1. [ ] `merger apply --mapping ... --out ... --format ...` çalışır.
2. [ ] `review` kalırsa apply durur ve uyarır (kör birleştirme yok).
3. [ ] `merged.<fmt>` + `merge_report.xlsx` üretilir; provenance eklidir.
4. [ ] Faz 2'de LLM çağrısı YOK.
5. [ ] E2E test geçer; `pytest` yeşil. **Uçtan uca MVP çalışır.**

## 7. Önceki Aşama Doğrulama Kontrol Listesi (Aşama 3b / 3a)
- [ ] `core/transformer.py` doğru dikey birleşik tablo üretiyor mu (TR/EN normalize testli)?
- [ ] `core/writer.py` xlsx/csv/sql + provenance + merge_report üretiyor mu?
- [ ] Faz 2'de LLM çağrısı yok mu?
- [ ] `pytest` yeşil mi?

Eksik varsa önce gider, kısa rapor yaz, sonra 3c'ye başla.

## 8. Teslim
`apply` çıktısı (başarılı + review-guard durması), üretilen dosyalar, E2E test sonucu,
`pytest` çıktısı, kabul kriterleri ✓/✗.
> **Bu noktada uçtan uca çalışan MVP hazır** (entity resolution hariç).
