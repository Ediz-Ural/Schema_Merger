# Codex Promptu — Aşama 6a: Web UI — FastAPI Backend

> **Kendi kendine yeter prompt.** Referans: `Project_Pdf/schema-merger-spec.pdf` v1.0.
> **Temiz Codex oturumunda çalıştır.** Önce §7 doğrulamasını yap.

## 0. Bağlam
Çekirdek + CLI stabil ve dokümante. Şimdi Web UI (Belge Bölüm 12 Aşama 6). **Kritik ilke
(Belge Bölüm 8):** UI ve CLI **aynı çekirdeği** kullanır — iş mantığı iki kez yazılmaz.
Bu parça backend: FastAPI, çekirdeği saran ince bir API katmanı.

## 1. Amaç
`web/backend/`: çekirdek fonksiyonları (analyze/apply, entity küme onayı) HTTP üzerinden
sunan FastAPI uygulaması. **Yeni iş mantığı yok** — yalnızca sunum/orkestrasyon.

## 2. Oluşturulacak / Değiştirilecek Dosyalar
```
web/backend/main.py       # FastAPI app
web/backend/routes.py     # endpoint'ler (upload, analyze, mapping getir/güncelle, apply, indir)
web/backend/schemas.py    # request/response modelleri (pydantic)
web/backend/__init__.py
tests/test_web_backend.py
pyproject.toml            # fastapi + uvicorn bağımlılıkları
```

## 3. Gereksinimler
- Endpoint'ler (öneri):
  - `POST /upload` — girdi dosyaları + schema.yaml al.
  - `POST /analyze` — çekirdeğin `analyze`'ını çağır → mapping (auto/review/unmatched) döndür.
  - `GET/PUT /mapping` — planı getir/güncelle (kullanıcı review/unmatched çözer).
  - `POST /apply` — **review kalırsa 4xx ile reddet** (kör birleştirme yok); yoksa çalıştır.
  - `GET /download` — `merged.<fmt>` + `merge_report.xlsx` indir.
  - (Entity varsa) küme onayı endpoint'i.
- **Çekirdeği doğrudan çağırır** — mantığı kopyalamaz.
- API key backend'de **env'den**; asla repoya/response'a sızmaz. İstemciden key alınacaksa
  bellek içi/oturum bazlı, diske yazılmaz — dokümante et.
- Uzun işlemler için basit ilerleme/durum yeterli (MVP; karmaşık kuyruk gerekmez).

## 4. Değişmez Kısıtlar (Belge Bölüm 14)
- UI ve CLI aynı çekirdeği paylaşır; iş mantığı tekrarlanmaz.
- `apply`, `review` kalırsa durur — API bunu 4xx ile zorlar.
- İki fazlı akış korunur; provenance her zaman.
- API key asla repoya/response'a girmez.

## 5. Testler
- [ ] `/analyze` (FakeLLM ile) geçerli mapping döndürüyor.
- [ ] `/apply` review varken **reddediyor** (4xx); tümü auto iken çalışıyor.
- [ ] `/mapping` PUT ile plan güncellenebiliyor.
- [ ] `/download` üretilen dosyaları veriyor.
- [ ] Key response'ta sızmıyor; env yoksa net hata.

## 6. Kabul Kriterleri
1. [ ] FastAPI backend çekirdeği sarar; yeni iş mantığı yok.
2. [ ] analyze/mapping/apply/download akışı HTTP üzerinden çalışır.
3. [ ] review-guard API seviyesinde uygulanır (4xx).
4. [ ] Key güvenliği korunur (env, sızıntı yok).
5. [ ] `pytest` yeşil, gerçek API çağrısı yok.

## 7. Önceki Aşama Doğrulama Kontrol Listesi (Aşama 5 — Cilalama)
- [ ] Validator + kenar durumlar çözülü ve testli mi?
- [ ] README (kurulum, key uyarısı, analyze/apply örnekleri, Değişmez Kararlar Özeti) tam mı?
- [ ] LICENSE MIT mi?
- [ ] `pytest` yeşil, kapsam tatmin edici mi?

Eksik varsa önce gider, kısa rapor yaz, sonra 6a'ya başla.

## 8. Teslim
Çalışan backend, endpoint listesi, `pytest` çıktısı, kabul kriterleri ✓/✗.
