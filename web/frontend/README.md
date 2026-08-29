# Schema Merger — Web UI (Aşama 6b)

Teknik olmayan kullanıcı için görsel onay ekranı. React + TypeScript + Vite; iş
mantığı yoktur — her karar `web/backend` (Aşama 6a) üzerinden aynı çekirdeğe
gider.

## Çalıştırma

İki süreç gerekir: backend ve frontend.

```bash
# 1) Backend (proje kökünde)
pip install -e ".[web]"
uvicorn web.backend.main:app --reload        # http://127.0.0.1:8000

# 2) Frontend (bu klasörde)
npm install
npm run dev                                  # http://localhost:5173
```

Vite dev sunucusu `/api/*` isteklerini `http://127.0.0.1:8000` adresine
yönlendirir; bu yüzden tarayıcı tek origin görür. Backend farklı bir adresteyse:

```bash
VITE_API_TARGET=http://127.0.0.1:9000 npm run dev   # dev proxy hedefi
VITE_API_BASE=https://api.example.com npm run build # derlenmiş dağıtım
```

Derlenmiş dağıtımda backend'in `SCHEMA_MERGER_CORS_ORIGINS` değişkenine
frontend'in origin'ini eklemeyi unutmayın.

## Hesap ve API anahtarı

İlk açılışta giriş ekranı gelir: **hesap oluştur** (e-posta + en az 8 karakter
parola) ya da **giriş yap**. Giriş sonrası üst çubuktaki sağlayıcı rozetinden
ayarlar açılır ve kullanıcı **kendi sağlayıcısını, modelini ve API anahtarını**
girer (`PUT /provider`).

Anahtar tarayıcıda **hiç saklanmaz**: bir kez sunucuya gönderilir ve orada
yalnızca süreç belleğinde tutulur; hiçbir yanıtta geri gelmediği için ayarlar
alanı boş görünür — boş bırakmak "kayıtlı anahtarı koru" demektir. `localStorage`
yalnızca oturum token'ını tutar. Çıkış yapınca ya da sunucu yeniden başlayınca
anahtar unutulur ve yeniden girilir.

Anahtar tanımlı değilken "Analiz et" pasiftir ve ekran ayarlara yönlendirir;
sunucu `503 llm_not_configured` dönerse ayarlar penceresi kendiliğinden açılır.

## Akış

1. **Yükle** — kaynak tablolar (`.csv`, `.xlsx`) + `schema.yaml` → `POST /upload`.
2. **Analiz** — `POST /analyze` planı üretir (LLM yalnızca burada), `GET /columns`
   düzeltme dropdown'ını dolduracak gerçek sütunları getirir.
3. **Onay** — plan kart olarak gösterilir:

   | Kart | Durum | Anlamı |
   | --- | --- | --- |
   | 🟢 yeşil | `auto` | Otomatik eşleşti, onaylı. |
   | 🟡 sarı | `review` | Karar sizde; **birleştirmeyi durdurur**. |
   | 🔴 kırmızı | `unmatched` | Eşleşme yok; sütun seçin ya da boş bırakın. |

   Her kartta hedef sütun, kaynak dosya, güven yüzdesi, gerekçe ve örnek
   değerler görünür. Düzeltme dropdown iledir: seçenekler o dosyada **gerçekten
   var olan** sütunlardır; `(boş bırak)` bilinçli olarak eşlememek demektir.
   Düzenlemeler `PUT /mapping` ile yazılır.
4. **Birleştir** — `POST /apply`. Buton **yalnızca hiç `review` kalmadığında**
   aktiftir; backend aynı kuralı `409` ile uygular, o yanıt geldiğinde ekran
   nedenini ve "hiçbir dosya yazılmadı" bilgisini gösterir.
5. **İndir** — `merged.<fmt>` ve `merge_report.xlsx` bağlantıları.

## Değişmezler

- Ekran hiçbir eşleştirme kararı üretmez; profil, eşleştirme, validator ve
  tekilleştirme backend'deki çekirdekte kalır.
- Her istek `Authorization: Bearer <token>` taşır; oturum düşerse (401) ekran
  giriş formuna döner ve token silinir. Çıktı indirmeleri de aynı token'la
  çekilir, bu yüzden bağlantı değil buton olarak sunulur.
- "Birleştir" review varken pasiftir (kör birleştirme yok) ve iki fazlı akış
  ekranda görünür: önce plan onayı, sonra birleştirme.
- API anahtarı tarayıcıda saklanmaz ve sunucudan geri gelmez. `GET /provider`
  yalnızca sağlayıcıyı, modeli ve anahtarın tanımlı olup olmadığını döndürür.
- Entity resolution (`cluster`) bu ekranda yoktur; CLI ya da API ile yapılır ve
  `apply` onaylı kümeleri yine uygular.

## Testler

```bash
npm test          # vitest + Testing Library (backend mock'lanır)
npm run build     # tsc --noEmit + vite build
```

Testler ağa çıkmaz: `src/api.ts` mock'lanır. Kapsananlar: giriş/kayıt akışı ve
reddedilen girişin kullanıcıya iletilmesi, anahtar girilmeden analizin
engellenmesi, girilen anahtarın sunucuya gidip tarayıcıda kalmaması, kart
renkleri, review varken "Birleştir" pasif / çözülünce aktif, dropdown
düzeltmesinin `PUT /mapping` çağrısına dönüşmesi, apply sonrası indirme
düğmeleri, `409` yanıtının açıklanması ve oturum düşünce giriş formuna dönüş.
