# Codex Promptu — Aşama 3b: Writer (Çıktı + Provenance + Rapor)

> **Kendi kendine yeter prompt.** Referans: `Project_Pdf/schema-merger-spec.pdf` v1.0.
> **Temiz Codex oturumunda çalıştır.** Önce §7 doğrulamasını yap.

## 0. Bağlam
Aşama 3a (Transformer) birleşik tabloyu üretti. Writer bunu diske yazar + provenance
sütunları ekler + `merge_report` üretir (Belge Bölüm 5, 7). **LLM YOK.**

## 1. Amaç
`core/writer.py`: birleşik tabloyu `xlsx | csv | sql` olarak yaz; provenance sütunlarını
ekle; ayrıca `merge_report.xlsx` üret (neyin nasıl eşleştiği, kaç satır geldi, kaç null
oluştu, entity'de belirsiz kalanlar — entity Aşama 4'te dolacak, alanları şimdi hazırla).

## 2. Oluşturulacak / Değiştirilecek Dosyalar
```
core/writer.py        # birleşik tablo -> xlsx/csv/sql + provenance + merge_report
tests/test_writer.py
```

## 3. Gereksinimler
- Çıktı formatları: `xlsx`, `csv`, `sql`. SQL = **CREATE TABLE + INSERT script** (Belge
  Bölüm 2/7 — MVP'de basit tutulur; canlı DB'ye yazma YOK).
- **Provenance sütunları her zaman eklenir** (Belge Bölüm 14/6): her satır için kaynak
  dosya + orijinal sütun ismi. `schema.yaml`'daki `output.add_provenance` saygı görür ama
  değişmez kural provenance'ın eklenmesidir; dokümante et.
- `merge_report.xlsx`: hedef sütun bazında eşleşme özeti (kaynak, confidence, status),
  satır sayıları, null sayıları/oranı. Entity belirsizleri için bölüm/kolon rezerve et.
- İki çıktı dosyası netçe ayrılır: `merged.<fmt>` (temiz veri) ve `merge_report.xlsx` (rapor).

## 4. Değişmez Kısıtlar (Belge Bölüm 14)
- **LLM YOK.**
- Provenance sütunları her zaman eklenir.
- Sadece dikey birleştirme sonucu yazılır.
- SQL çıktısı script'tir; canlı DB bağlantısı yok.

## 5. Testler
- [ ] `xlsx`, `csv`, `sql` çıktıları üretiliyor; içerik birleşik tabloyla tutarlı.
- [ ] Provenance sütunları çıktıda mevcut ve doğru köken gösteriyor.
- [ ] `merge_report` satır/null sayılarını doğru raporluyor (bilinen fixture).
- [ ] SQL çıktısı geçerli CREATE TABLE + INSERT üretiyor (parse/smoke test).

## 6. Kabul Kriterleri
1. [ ] `core/writer.py` xlsx/csv/sql yazar; provenance her zaman eklenir.
2. [ ] `merge_report.xlsx` eşleşme + satır/null özetini içerir.
3. [ ] SQL = CREATE TABLE + INSERT (basit, canlı DB yok).
4. [ ] LLM çağrısı YOK.
5. [ ] `pytest` yeşil.

## 7. Önceki Aşama Doğrulama Kontrol Listesi (Aşama 3a)
- [ ] `core/transformer.py` onaylı mapping'den doğru dikey birleşik tablo üretiyor mu?
- [ ] TR/EN sayı-tarih normalizasyonu testli çalışıyor mu?
- [ ] Provenance köken bilgisi taşınıyor mu?
- [ ] LLM çağrısı yok, `pytest` yeşil mi?

Eksik varsa önce gider, kısa rapor yaz, sonra 3b'ye başla.

## 8. Teslim
Örnek `merged.xlsx`/`.csv`/`.sql` + `merge_report.xlsx`, `pytest` çıktısı, kabul kriterleri ✓/✗.
