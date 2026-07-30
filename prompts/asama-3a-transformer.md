# Codex Promptu — Aşama 3a: Transformer (Deterministik Dikey Birleştirme)

> **Kendi kendine yeter prompt.** Referans: `Project_Pdf/schema-merger-spec.pdf` v1.0.
> **Temiz Codex oturumunda çalıştır.** Önce §7 doğrulamasını yap.

## 0. Bağlam
Aşama 2 tamam: `analyze` → `mapping.yaml`. Şimdi **Faz 2 (LLM YOK, deterministik)** başlar.
Transformer, onaylı plana göre veriyi dönüştürüp dikey birleştirir (Belge Bölüm 5, 7).

## 1. Amaç
`core/transformer.py`: onaylı `mapping.yaml`'ı alıp kaynak dosyalardaki satırları hedef
şemaya taşı, tip/format normalize et, **dikey (union) birleştir**, provenance için gerekli
köken bilgisini hazırla. **Bu kod tamamen deterministik — LLM yok.**

## 2. Oluşturulacak / Değiştirilecek Dosyalar
```
core/transformer.py   # mapping + kaynak veriler -> birleşik tablo (in-memory / DataFrame)
core/normalize.py     # TR/EN sayı-tarih format normalizasyonu (Aşama 1'den varsa genişlet)
tests/test_transformer.py
tests/fixtures/        # bilinen değerlerle 2 kaynak dosya + onaylı mapping.yaml
```

## 3. Gereksinimler
- Girdi: onaylı `mapping.yaml` + kaynak dosyalar. Çıktı: tek birleşik tablo (satırlar alt alta).
- Her hedef sütun için, mapping'deki kaynak sütunlardan değerleri çeker.
- **TR/EN normalizasyon (olmazsa olmaz — Belge Bölüm 11):** `"12,50"`→`12.50`, binlik
  `"1.234,56"`→`1234.56`; TR tarih `gg.aa.yyyy` ↔ ISO. Hedef `type`'a göre tip çevrimi.
- **Provenance için** her satırın hangi kaynak dosya + orijinal sütundan geldiğini izle
  (fiili sütun ekleme Writer'da olabilir; Transformer bu bilgiyi taşımalı).
- Büyük dosya için streaming/chunked işlemeye uygun tasarla (Polars önerilir — Belge Bölüm 7).
- **Veri bozulmaz:** dönüştürülemeyen değer sessizce silinmez; null/işaretli bırakılır ve
  rapora yansıyacak şekilde sayılır.

## 4. Değişmez Kısıtlar (Belge Bölüm 14)
- **LLM YOK** — Faz 2 saf deterministik kod.
- Sadece dikey (union) birleştirme; yatay join yok.
- Veri sessizce bozulmaz; dönüşüm hataları izlenir.
- Provenance bilgisi her satır için korunur.

## 5. Testler
- [ ] Bilinen 2 kaynak + onaylı mapping → beklenen satır sayısı (A+B) ve değerler.
- [ ] TR sayı formatı doğru çevriliyor (`"12,50"`→12.50; `"1.234,56"`→1234.56).
- [ ] TR/ISO tarih normalizasyonu doğru.
- [ ] `unmatched`/boş kaynak → hedef sütun null, satır kaybı yok.
- [ ] Provenance köken bilgisi her satırda mevcut.
- [ ] Dönüştürülemeyen değer sessizce silinmiyor (null + sayaç).

## 6. Kabul Kriterleri
1. [ ] `core/transformer.py` onaylı mapping'den doğru birleşik tablo üretir (deterministik).
2. [ ] TR/EN sayı-tarih normalizasyonu çalışır ve testlidir.
3. [ ] Provenance köken bilgisi taşınır.
4. [ ] LLM çağrısı YOK.
5. [ ] `pytest` yeşil.

## 7. Önceki Aşama Doğrulama Kontrol Listesi (Aşama 2c / Aşama 2)
- [ ] `merger analyze ...` çalışıp geçerli `mapping.yaml` üretiyor mu?
- [ ] Konsol özeti auto/review/unmatched sayılarını basıyor mu?
- [ ] `mapping.yaml` `contracts` ile yeniden yüklenebiliyor mu?
- [ ] `pytest` yeşil mi, gerçek API çağrısı yok mu?

Eksik varsa önce gider, kısa rapor yaz, sonra 3a'ya başla.

## 8. Teslim
Oluşturulan dosyalar, `pytest` çıktısı, örnek birleştirme sonucu, kabul kriterleri ✓/✗.
