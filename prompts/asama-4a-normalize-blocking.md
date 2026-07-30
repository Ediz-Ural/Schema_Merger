# Codex Promptu — Aşama 4a: Entity Resolution — Normalizasyon + Blocking

> **Kendi kendine yeter prompt.** Referans: `Project_Pdf/schema-merger-spec.pdf` v1.0.
> **Temiz Codex oturumunda çalıştır.** Önce §7 doğrulamasını yap.

## 0. Bağlam
Uçtan uca MVP (Aşama 3) çalışıyor. Şimdi en zor parça: **Entity Resolution** — aynı ürünün
farklı yazımlarını tekilleştirme (Belge Bölüm 4, 7). Dört katmanlı; bu parça **ilk iki
deterministik katman**: Normalizasyon + Blocking. **LLM YOK bu parçada.**

## 1. Amaç
`core/entity.py`'ın ilk iki katmanını kur:
1. **Normalizasyon (kod):** lowercase, birim çevirme (`33cl`→`330ml`), noktalama temizleme,
   kısaltma açma. (Belge Bölüm 7)
2. **Blocking (kod):** tüm-çiftler yerine yalnızca aynı blok (ör. ilk 3 harf / kategori /
   marka) — milyon×milyon → milyon×onlarca. Ölçek patlamasını önler.

## 2. Oluşturulacak / Değiştirilecek Dosyalar
```
core/entity.py        # normalize() + blocking() katmanları (bu parça)
tests/test_entity_normalize.py
tests/test_entity_blocking.py
tests/fixtures/        # aynı ürünün varyantları (Coca Cola 330ml / Coca-Cola Kutu 33cl vb.)
```

## 3. Gereksinimler
- `normalize(value) -> str`: deterministik, TR odaklı (Türkçe karakter/kısaltma). Birim
  dönüşüm tablosu config'lenebilir; varsayılanlar dokümante.
- `make_blocks(records) -> dict[block_key, list]`: blocking anahtarı stratejisi seçilebilir
  (ilk N harf / kategori / marka). Amaç: karşılaştırma uzayını küçültmek.
- **LLM satır seviyesinde çağrılamaz** — bu katmanlar tamamen kod. LLM sonraki parçada
  (4b) sadece gri bölge için.
- Performans bilinçli: büyük veri için makul; tüm-çift karşılaştırması YASAK.

## 4. Değişmez Kısıtlar (Belge Bölüm 14)
- LLM satır seviyesinde çalışmaz (bu parçada LLM hiç yok).
- Veri sessizce değiştirilmez — normalizasyon **karşılaştırma için** üretilir; orijinal
  değer korunur (provenance bozulmaz).
- Sadece dikey birleştirme bağlamı.

## 5. Testler
- [ ] `33cl` ↔ `330ml` normalize sonrası eşdeğer; `Coca Cola` ≈ `Coca-Cola Kutu`.
- [ ] Türkçe karakter/kısaltma normalizasyonu doğru.
- [ ] Blocking aynı ürün varyantlarını aynı bloğa koyuyor; alakasızları ayırıyor.
- [ ] Orijinal değerler değişmeden korunuyor (normalize yalnız karşılaştırma için).
- [ ] Tüm-çift karşılaştırması yapılmadığı doğrulanıyor (blok bazlı).

## 6. Kabul Kriterleri
1. [ ] `core/entity.py` deterministik `normalize` + `blocking` sağlar.
2. [ ] Birim/kısaltma/noktalama normalizasyonu testlidir.
3. [ ] Blocking karşılaştırma uzayını daraltır; tüm-çift yok.
4. [ ] Orijinal veri korunur; LLM çağrısı yok.
5. [ ] `pytest` yeşil.

## 7. Önceki Aşama Doğrulama Kontrol Listesi (Aşama 3 — MVP)
- [ ] `merger analyze` + `merger apply` uçtan uca çalışıyor mu?
- [ ] `apply`, `review` kalırsa duruyor mu (kör birleştirme yok)?
- [ ] `merged.<fmt>` + `merge_report.xlsx` + provenance üretiliyor mu?
- [ ] Faz 2'de LLM yok, `pytest` yeşil mi?

Eksik varsa önce gider, kısa rapor yaz, sonra 4a'ya başla.

## 8. Teslim
Oluşturulan dosyalar, normalize/blocking örnekleri, `pytest` çıktısı, kabul kriterleri ✓/✗.
