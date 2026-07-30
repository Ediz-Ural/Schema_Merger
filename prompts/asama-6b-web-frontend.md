# Codex Promptu — Aşama 6b: Web UI — React Onay Ekranı

> **Kendi kendine yeter prompt.** Referans: `Project_Pdf/schema-merger-spec.pdf` v1.0.
> **Temiz Codex oturumunda çalıştır.** Önce §7 doğrulamasını yap.

## 0. Bağlam
6a (FastAPI backend) hazır. Bu parça, teknik olmayan kullanıcı için görsel onay ekranı
(Belge Bölüm 12 Aşama 6): yeşil/sarı/kırmızı kartlar, dropdown ile düzeltme, "Birleştir"
butonu **ancak review kalmadığında aktif**.

## 1. Amaç
`web/frontend/`: React uygulaması. Dosya yükle → analyze → eşleştirme planını **kart
tabanlı** göster → kullanıcı review/unmatched çözer → apply → indir. Backend'i (6a) çağırır;
iş mantığı içermez.

## 2. Oluşturulacak / Değiştirilecek Dosyalar
```
web/frontend/            # React proje iskeleti (Vite öneri)
  src/App.tsx
  src/api.ts             # backend çağrıları
  src/components/MappingCard.tsx   # yeşil/sarı/kırmızı kart
  src/components/...
web/frontend/README.md   # çalıştırma talimatı
```

## 3. Gereksinimler
- **Kart renk kodu (Belge Bölüm 6/12):**
  - `auto` → **yeşil** (otomatik eşleşti).
  - `review` → **sarı** (kullanıcı onaylamalı/düzeltmeli).
  - `unmatched` → **kırmızı** (kaynak sütun seç ya da "boş bırak").
- Her kartta: hedef sütun, kaynak(lar), confidence, gerekçe, örnek değerler.
- **Düzeltme:** mevcut sütunu **dropdown** ile seç (Belge Bölüm 7 — LLM'e gerek yok, kod
  eşler). Serbest metin yeni isim ise backend'in katmanlı aramasını tetikler (öneri getirir).
- **"Birleştir" butonu yalnızca hiç `review` kalmadığında aktif** (kör birleştirme yok).
- Sonuç: `merged` + `merge_report` indirme linkleri.
- Tüm iş mantığı backend'de; frontend yalnızca sunum + kullanıcı etkileşimi.

## 4. Değişmez Kısıtlar (Belge Bölüm 14)
- UI aynı çekirdeği (backend üzerinden) kullanır; mantık kopyalanmaz.
- "Birleştir" ancak review kalmayınca aktif — HITL ve review-guard korunur.
- İki fazlı akış görünür: önce plan onayı, sonra birleştirme.
- Key kullanıcı arayüzünde güvenli ele alınır; repoya/loglara sızmaz.

## 5. Testler
- [ ] Kart renkleri status'a göre doğru (auto/review/unmatched → yeşil/sarı/kırmızı).
- [ ] En az bir review varken "Birleştir" **disabled**; tümü çözülünce **enabled**.
- [ ] Dropdown ile sütun düzeltme mapping'i güncelliyor (backend PUT çağrısı).
- [ ] apply sonrası indirme linkleri görünüyor.
- [ ] (Bileşen/entegrasyon testleri; backend mock'lanabilir.)

## 6. Kabul Kriterleri
1. [ ] React onay ekranı: yeşil/sarı/kırmızı kartlar + gerekçe + örnekler.
2. [ ] Dropdown ile düzeltme; "Birleştir" yalnızca review kalmayınca aktif.
3. [ ] analyze→onay→apply→indir akışı uçtan uca çalışır (backend ile).
4. [ ] İş mantığı frontend'de yok; testler geçer.
5. [ ] **Teknik olmayan kullanıcı için görsel arayüz hazır — proje tamamlanır.**

## 7. Önceki Aşama Doğrulama Kontrol Listesi (Aşama 6a)
- [ ] FastAPI backend çekirdeği sarıyor, yeni iş mantığı yok mu?
- [ ] analyze/mapping/apply/download akışı HTTP'den çalışıyor mu?
- [ ] review-guard API'de 4xx ile uygulanıyor mu?
- [ ] Key güvenliği korunuyor, `pytest` yeşil mi?

Eksik varsa önce gider, kısa rapor yaz, sonra 6b'ye başla.

## 8. Teslim
Çalışan frontend, ekran görüntüsü/akış özeti, test çıktısı, kabul kriterleri ✓/✗.
