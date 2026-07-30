# Codex Promptu — Aşama 5b: Cilalama — Kenar Durumlar, Testler, Dokümantasyon

> **Kendi kendine yeter prompt.** Referans: `Project_Pdf/schema-merger-spec.pdf` v1.0.
> **Temiz Codex oturumunda çalıştır.** Önce §7 doğrulamasını yap.

## 0. Bağlam
Validator (5a) eklendi. Bu parça projeyi **sağlamlaştırılmış, dokümante edilmiş sürüme**
taşır (Belge Bölüm 12 Aşama 5): kenar durumlar, test kapsamı, README, LICENSE.

## 1. Amaç
Kenar durumları çöz, test kapsamını genişlet, dokümantasyonu tamamla. Yeni özellik değil —
**sağlamlaştırma ve cilalama**.

## 2. Oluşturulacak / Değiştirilecek Dosyalar
```
README.md             # tam kullanım: analyze/apply, key uyarısı, çok-sheet davranışı, örnekler
LICENSE               # MIT (varsa doğrula)
core/*.py             # kenar durum düzeltmeleri (davranış değişmez, sağlamlaşır)
tests/                # kapsam genişletme + kenar durum testleri
docs/ veya README     # veri sözleşmeleri (schema.yaml/mapping.yaml) referansı
```

## 3. Gereksinimler — Kenar Durumlar (Belge Bölüm 11)
- **Çok-sheet'li Excel:** davranış net (kullanıcı sheet belirtir ya da hepsi taranır) ve
  README'de dokümante; testli.
- **Çakışan değerler:** hepsi tutulur + provenance ile işaretlenir; **otomatik "doğrusunu
  seçme" YOK** (kapsam dışı).
- **Tip çatışmaları:** TR/EN sayı-tarih normalizasyonu sağlam; bozuk değer sessizce
  silinmez, raporlanır.
- **Key yoksa** açık hata mesajı (Belge Bölüm 9) — testli.
- Bonus (öneri, zorunlu değil): commit öncesi sızıntı taraması notu (git-secrets/pre-commit).

## 4. Değişmez Kısıtlar (Belge Bölüm 14 — hepsi korunur)
1. Sadece dikey birleştirme. 2. analyze→onay→apply. 3. LLM satır verisini işlemez.
4. confidence+status+gerekçe. 5. review kalırsa apply durur. 6. provenance her zaman.
7. key asla repoya girmez. 8. çekirdek+CLI önce, UI aynı çekirdeği paylaşır.
> README'de "Değişmez Kararlar Özeti" (Belge Bölüm 14) yer almalı.

## 5. Testler
- [ ] Çok-sheet Excel: `--sheet` ile tek sheet ve tümünü tarama testli.
- [ ] Çakışan değerler korunuyor + provenance ile işaretli (otomatik seçim yok).
- [ ] Key yok senaryosu açık hata veriyor.
- [ ] Genel test kapsamı anlamlı; `pytest` yeşil.
- [ ] README örnekleri (analyze→apply) gerçekten çalışıyor (smoke).

## 6. Kabul Kriterleri
1. [ ] Kenar durumlar (çok-sheet, çakışan değer, tip çatışması, key yok) çözülü + testli.
2. [ ] README: kurulum + key uyarısı + analyze/apply örnekleri + çok-sheet davranışı +
   veri sözleşmeleri + Değişmez Kararlar Özeti içerir.
3. [ ] LICENSE MIT.
4. [ ] `pytest` yeşil, kapsam tatmin edici.
5. [ ] **Sağlamlaştırılmış, dokümante edilmiş sürüm hazır.**

## 7. Önceki Aşama Doğrulama Kontrol Listesi (Aşama 5a)
- [ ] `core/validator.py` tip/null/format/aykırı denetimlerini yapıyor mu?
- [ ] Ciddi bulgular `review`'a düşüyor, apply guard'ı saygı gösteriyor mu?
- [ ] Bulgular `merge_report`'a yazılıyor, veri sessizce değişmiyor mu?
- [ ] LLM yok, `pytest` yeşil mi?

Eksik varsa önce gider, kısa rapor yaz, sonra 5b'ye başla.

## 8. Teslim
Güncellenen README/LICENSE, kenar durum testleri, `pytest` çıktısı, kabul kriterleri ✓/✗.
