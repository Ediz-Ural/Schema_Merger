# Schema Merger — Codex Aşama Promptları

Bu klasör, `Project_Pdf/schema-merger-spec.pdf` (Proje Spesifikasyonu v1.0) yol
haritasının her aşaması için **Codex'e verilecek kendi kendine yeten promptları** içerir.

## Kullanım Felsefesi — Optimize + Temiz Oturum

Her prompt **tek başına, sıfırdan (temiz context) bir Codex oturumunda** çalıştırılmak
üzere tasarlandı. Amaç: bağlam biriktirmeden (cache/context şişmeden) her adımı dar ve
net tutmak.

**Her yeni prompta başlarken:**
1. Codex oturumunu **temizle / yeni oturum başlat** (önceki bağlamı taşıma).
2. İlgili prompt dosyasını yapıştır.
3. Prompt içindeki **"Önceki Aşama Doğrulama Kontrol Listesi"** ile önceki adımın
   gerçekten tamamlandığını doğrulat; eksik varsa önce onu giderttir.
4. Aşamayı bitir, kabul kriterlerini raporlat, oturumu kapat.

> Referans kaynak her zaman `Project_Pdf/schema-merger-spec.pdf`'tir. Promptla belge
> çelişirse belge kazanır.

## Sıra (çekirdek-önce)

| # | Prompt | Yol Haritası Aşaması | Kısaca |
|---|--------|----------------------|--------|
| 1 | `asama-1-iskelet-profiler.md` | 1 — İskelet + Veri Katmanı | Repo iskeleti, güvenlik, Profiler |
| 2a | `asama-2a-llm-ve-veri-sozlesmeleri.md` | 2 — Matcher + Plan | LLM soyutlama katmanı + schema.yaml/mapping.yaml sözleşmeleri |
| 2b | `asama-2b-matcher.md` | 2 — Matcher + Plan | LLM ile sütun eşleştirme (confidence/status/gerekçe) |
| 2c | `asama-2c-analyze-komutu.md` | 2 — Matcher + Plan | `analyze` CLI komutu + konsol özeti |
| 3a | `asama-3a-transformer.md` | 3 — Transformer + Writer | Deterministik dikey birleştirme + provenance |
| 3b | `asama-3b-writer.md` | 3 — Transformer + Writer | xlsx/csv/sql çıktı + merge_report |
| 3c | `asama-3c-apply-komutu.md` | 3 — Transformer + Writer | `apply` CLI + review-guard → uçtan uca MVP |
| 4a | `asama-4a-normalize-blocking.md` | 4 — Entity Resolution | Normalizasyon + Blocking (kod) |
| 4b | `asama-4b-embedding-gri-bolge-llm.md` | 4 — Entity Resolution | Embedding + eşik + gri bölge LLM |
| 4c | `asama-4c-kume-raporu-onay.md` | 4 — Entity Resolution | Küme raporu + küme bazlı onay |
| 5a | `asama-5a-validator.md` | 5 — Validator + Cilalama | Tip/null/format tutarlılık denetimi |
| 5b | `asama-5b-cilalama-dokuman.md` | 5 — Validator + Cilalama | Kenar durumlar, testler, README, LICENSE |
| 6a | `asama-6a-web-backend.md` | 6 — Web UI | FastAPI backend (çekirdeği sarar) |
| 6b | `asama-6b-web-frontend.md` | 6 — Web UI | React onay ekranı |

## Değişmez Kararlar (hiçbir promptta ihlal edilmez — Belge Bölüm 14)

1. Sadece dikey (union) birleştirme.
2. İki fazlı akış: `analyze` (LLM) → kullanıcı onayı → `apply` (LLM yok).
3. LLM yalnızca sütun eşleştirmede ve entity gri bölgesinde; asla satır verisini elle işlemez.
4. Her eşleştirme `confidence` + `status` (auto/review/unmatched) + gerekçe taşır.
5. `apply`, `review` kalırsa durur — kör birleştirme yok.
6. Provenance sütunları her zaman eklenir.
7. API key asla repoya girmez (`.env` + `.gitignore` + `.env.example`).
8. Çekirdek + CLI önce, UI sonra; UI ve CLI aynı çekirdeği paylaşır.
