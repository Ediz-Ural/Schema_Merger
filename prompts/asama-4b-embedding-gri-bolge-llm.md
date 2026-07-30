# Codex Promptu — Aşama 4b: Entity Resolution — Embedding + Gri Bölge LLM

> **Kendi kendine yeter prompt.** Referans: `Project_Pdf/schema-merger-spec.pdf` v1.0.
> **Temiz Codex oturumunda çalıştır.** Önce §7 doğrulamasını yap.

## 0. Bağlam
Aşama 4a: normalize + blocking hazır. Bu parça 3. ve 4. katmanı ekler: **Embedding + eşik**
(ucuz) ve **gri bölge LLM** (pahalı, nadir — toplam kayıtların ~%1–5'i) (Belge Bölüm 7).

## 1. Amaç
Blok içi çiftleri embedding benzerliği ile skorla; eşiklere göre karar ver:
- Yüksek benzerlik → **aynı** (otomatik).
- Düşük benzerlik → **farklı** (otomatik).
- **Eşiğe yakın gri bölge** → LLM'e sor (yalnızca burada, nadiren).

## 2. Oluşturulacak / Değiştirilecek Dosyalar
```
core/entity.py        # embedding + eşik + gri bölge LLM katmanları (4a'ya ekle)
core/llm.py           # gerekiyorsa embedding/karar yardımcı arayüzü ekle
tests/test_entity_embedding.py
tests/test_entity_grey_llm.py
```

## 3. Gereksinimler
- Blok içi vektör benzerliği (embedding). Sağlayıcı `core/llm.py` üzerinden soyutlanır;
  local (Ollama/Qwen) dahil config'lenebilir (Belge Bölüm 7 "veriniz hiçbir yere gitmesin").
- İki eşik: `high` (üstü → aynı), `low` (altı → farklı). Arası = **gri bölge**.
- Gri bölge çiftleri **LLM'e** sorulur; LLM yalnızca **öneri getirici** — kararı kesinleştiren
  kullanıcıdır (küme onayı 4c'de). Gri bölge oranı ~%1–5 hedeflenir; ölçek patlamaz.
- LLM yanıtı bozuk/güvensizse → çift gri/incelenecek kalır, sessizce "aynı" sayılmaz.

## 4. Değişmez Kısıtlar (Belge Bölüm 14)
- LLM **satır verisini işlemez**; yalnızca "bu iki ürün aynı mı?" öneri kararı verir.
- LLM yalnızca gri bölgede — satır seviyesinde toplu çağrı YOK (ölçek prensibi).
- Belirsizler otomatik birleşmez; kullanıcı onayına kalır.
- Provenance/orijinal veri korunur.

## 5. Testler
- [ ] Yüksek benzerlik → aynı; düşük → farklı (eşik testleri, FakeEmbedding ile).
- [ ] Gri bölge çiftleri tespit ediliyor ve yalnızca onlar LLM'e gidiyor.
- [ ] Gri bölge oranının makul (küçük) kaldığı bilinen fixture'da doğrulanıyor.
- [ ] Bozuk/güvensiz LLM yanıtı → çift "aynı" sayılmıyor, incelenecek kalıyor.
- [ ] Gerçek API/embedding çağrısı yok (mock/fake).

## 6. Kabul Kriterleri
1. [ ] Embedding + iki eşik ile aynı/farklı/gri karar mekanizması çalışır.
2. [ ] Yalnızca gri bölge LLM'e gider; oran küçük.
3. [ ] LLM öneri getirici; belirsiz → kullanıcı onayına kalır (otomatik birleşme yok).
4. [ ] Gerçek API çağrısı olmadan testler geçer (`pytest` yeşil).

## 7. Önceki Aşama Doğrulama Kontrol Listesi (Aşama 4a)
- [ ] `core/entity.py` deterministik normalize + blocking sağlıyor mu?
- [ ] Birim/kısaltma normalizasyonu ve blok bazlı karşılaştırma testli mi?
- [ ] Orijinal veri korunuyor, tüm-çift karşılaştırması yok mu?
- [ ] `pytest` yeşil mi?

Eksik varsa önce gider, kısa rapor yaz, sonra 4b'ye başla.

## 8. Teslim
Oluşturulan dosyalar, eşik/gri bölge örnekleri, `pytest` çıktısı, kabul kriterleri ✓/✗.
