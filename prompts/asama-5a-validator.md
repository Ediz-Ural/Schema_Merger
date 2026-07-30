# Codex Promptu — Aşama 5a: Validator (Tutarlılık Denetimi)

> **Kendi kendine yeter prompt.** Referans: `Project_Pdf/schema-merger-spec.pdf` v1.0.
> **Temiz Codex oturumunda çalıştır.** Önce §7 doğrulamasını yap.

## 0. Bağlam
Çekirdek + entity resolution oturdu. Validator, Matcher'ın kararını denetleyen **ayrı bir
göz** — kritik (Belge Bölüm 7). **LLM YOK.** Faz 2'de, apply öncesi/sırasında çalışır.

## 1. Amaç
`core/validator.py`: önerilen eşleştirmeyi ve birleşik veriyi **tip/format tutarlılığı,
aykırı değer, null patlaması** açısından denetle. Sorunları rapora ve gerektiğinde
`review`'a döndür.

## 2. Oluşturulacak / Değiştirilecek Dosyalar
```
core/validator.py     # tip/null/format tutarlılık + aykırı değer + null patlaması denetimi
cli/main.py           # apply akışına validator'ı bağla (Aşama 3c'deki temel guard'ı genişlet)
core/writer.py        # merge_report'a validator bulgularını ekle
tests/test_validator.py
```

## 3. Gereksinimler
- Denetimler:
  - **Tip tutarlılığı:** hedef `type` ile gelen değerler uyumlu mu (decimal/integer/date...).
  - **Null patlaması:** bir hedef sütunda beklenmedik yüksek null oranı → uyarı/flag.
  - **Aykırı değer:** sayısal sütunlarda kaba aralık/aykırı tespiti (deterministik, basit).
  - **Format:** TR/EN normalizasyon sonrası kalan bozuk formatlar.
- Bulgular `merge_report`'a yazılır. Ciddi tutarsızlık → ilgili eşleştirme **`review`'a
  düşürülebilir** (kör birleştirmeyi önler). Validator sessizce veri düzeltmez.
- `required: true` hedef sütun boşsa/eksikse net hata veya review.

## 4. Değişmez Kısıtlar (Belge Bölüm 14)
- **LLM YOK.**
- Validator veriyi sessizce değiştirmez; işaretler/raporlar/`review`'a döndürür.
- `apply`, çözülmemiş `review` kalırsa durur (guard korunur).
- Provenance korunur.

## 5. Testler
- [ ] Tip uyumsuzluğu (ör. decimal sütunda metin) tespit ediliyor.
- [ ] Null patlaması bilinen fixture'da flag'leniyor.
- [ ] Aykırı değer tespiti çalışıyor (basit aralık).
- [ ] `required` sütun boşsa hata/review üretiliyor.
- [ ] Bulgular `merge_report`'a yansıyor; validator veriyi değiştirmiyor.

## 6. Kabul Kriterleri
1. [ ] `core/validator.py` tip/null/format/aykırı denetimlerini yapar.
2. [ ] Ciddi bulgular `review`'a döndürülür; apply guard'ı buna saygı gösterir.
3. [ ] Bulgular `merge_report`'a yazılır; veri sessizce değişmez.
4. [ ] LLM çağrısı YOK; `pytest` yeşil.

## 7. Önceki Aşama Doğrulama Kontrol Listesi (Aşama 4 — Entity Resolution)
- [ ] normalize + blocking + embedding + gri LLM katmanları çalışıyor mu?
- [ ] Küme bazlı onay akışı var; belirsizler onaysız birleşmiyor mu?
- [ ] Tekilleştirme apply çıktısına yansıyor, `merge_report` belirsizleri gösteriyor mu?
- [ ] `pytest` yeşil mi, gri bölge LLM'i mock ile test edilmiş mi?

Eksik varsa önce gider, kısa rapor yaz, sonra 5a'ya başla.

## 8. Teslim
Oluşturulan dosyalar, örnek validator bulguları, `pytest` çıktısı, kabul kriterleri ✓/✗.
