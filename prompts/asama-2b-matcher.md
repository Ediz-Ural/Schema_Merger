# Codex Promptu — Aşama 2b: Matcher (LLM ile Sütun Eşleştirme)

> **Kendi kendine yeter prompt.** Referans: `Project_Pdf/schema-merger-spec.pdf` v1.0.
> **Temiz Codex oturumunda çalıştır.** Önce §7 doğrulamasını yap.

## 0. Bağlam
`schema-merger`: heterojen tabloları kullanıcı onaylı planla tek **dikey (union)** dosyaya
birleştiren araç. Aşama 1 (Profiler) ve 2a (LLM katmanı + veri sözleşmeleri) tamam. Şimdi
işin kalbi: **Matcher**.

## 1. Amaç
Hedef şema sütunlarını, profillenen kaynak sütunlarla eşleştir. Her eşleştirme için
`confidence + status + gerekçe` üret (Belge Bölüm 4, 6, 7 "Matcher: LLM burada").

**Kritik kural:** LLM yalnızca **plan** üretir (hangi kaynak sütun → hangi hedef sütun,
neden, ne kadar güven). LLM **asla veri satırı yazmaz/dönüştürmez**. Eşleştirme dört sinyale
dayanır (Belge Bölüm 4): sütun ismi, veri tipi, örnek değerler (5–10 satır LLM'e mutlaka
verilir), istatistiksel profil.

## 2. Oluşturulacak / Değiştirilecek Dosyalar
```
core/matcher.py       # Profiler çıktısı + hedef şema -> mapping girdileri (LLM ile)
core/types.py         # gerekirse MatchResult alanlarını genişlet
tests/test_matcher.py
tests/fixtures/        # 2 küçük kaynak dosya (farklı sütun isimleri: birim_fiyat / UF vb.)
```

## 3. Gereksinimler
- Girdi: Profiler'ın ürettiği kaynak sütun profilleri + `schema.yaml` hedef sütunları.
- Her hedef sütun için her kaynak dosyada bir eşleştirme adayı değerlendir.
- LLM'e verilecek bağlam: sütun ismi + tip + **5–10 örnek değer** + istatistik özeti.
- Çıktı: `mapping.yaml`'a yazılabilir yapı (Belge Bölüm 6 formatı):
  - `confidence` (0.0–1.0), `status`, `reason` (gerekçe), riskliler için `samples`.
- **Status atama eşiği (deterministik, kodda):** yüksek güven → `auto`; düşük/orta ve
  belirsiz → `review`; hiçbir kaynak sütun uymuyorsa → `unmatched`. Eşikler config'lenebilir,
  varsayılanlar dokümante edilir.
- **Dosya başına sabit LLM çağrısı** (satır sayısından bağımsız — Belge Bölüm 2 Ölçek Prensibi).
  LLM satır seviyesinde ÇAĞRILMAZ.
- LLM çıktısı parse edilirken savunmacı ol: bozuk/eksik JSON → o eşleştirme `review`'a düşer,
  asla sessizce `auto` olmaz.

## 4. Değişmez Kısıtlar (Belge Bölüm 14)
- LLM veriyi elle işlemez — yalnızca plan üretir.
- Her eşleştirme `confidence` + `status` + gerekçe taşır.
- Belirsiz/riskli her şey `review` (kör `auto` yok).
- Sadece dikey birleştirme kapsamı; yatay join önerme.
- LLM satır seviyesinde çalışmaz; dosya başına sabit çağrı.

## 5. Testler
- [ ] `FakeLLMClient` ile deterministik: bilinen girdi → beklenen mapping girdileri.
- [ ] Yüksek güven → `auto`; belirsiz → `review`; karşılıksız → `unmatched`.
- [ ] LLM'e örnek değerlerin gerçekten geçtiği doğrulanıyor (çağrı içeriği assert edilir).
- [ ] Bozuk LLM yanıtı → ilgili eşleştirme `review`'a düşüyor, çökme yok.
- [ ] Satır sayısı artınca LLM çağrı sayısı değişmiyor (ölçek prensibi regresyonu).

## 6. Kabul Kriterleri
1. [ ] `core/matcher.py` profiller + hedef şemadan `mapping.yaml`'a yazılabilir yapı üretir.
2. [ ] Her girdi `confidence + status + reason` taşır; riskliler `samples` içerir.
3. [ ] Status eşikleri deterministik ve dokümante; belirsizler `review`.
4. [ ] Gerçek API çağrısı olmadan testler geçiyor (`pytest` yeşil).
5. [ ] Dosya başına sabit çağrı — LLM satır seviyesinde çağrılmıyor.

## 7. Önceki Aşama Doğrulama Kontrol Listesi (Aşama 2a)
- [ ] `core/llm.py` var; key env'den okunuyor, yoksa açık hata; test'te gerçek çağrı yok mu?
- [ ] `core/contracts.py` schema.yaml + mapping.yaml load/validate/dump yapıyor mu (round-trip)?
- [ ] `.env.example` provider + key alanlarını içeriyor, `.env` repoda YOK mu?
- [ ] `pytest` yeşil mi?

Eksik varsa önce gider, kısa rapor yaz, sonra 2b'ye başla.

## 8. Teslim
Oluşturulan dosyalar, `pytest` çıktısı, örnek üretilmiş mapping girdisi, kabul kriterleri ✓/✗.
