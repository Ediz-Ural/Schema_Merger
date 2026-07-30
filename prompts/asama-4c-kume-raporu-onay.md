# Codex Promptu — Aşama 4c: Entity Resolution — Küme Raporu + Küme Bazlı Onay

> **Kendi kendine yeter prompt.** Referans: `Project_Pdf/schema-merger-spec.pdf` v1.0.
> **Temiz Codex oturumunda çalıştır.** Önce §7 doğrulamasını yap.

## 0. Bağlam
4a (normalize+blocking) ve 4b (embedding+gri LLM) hazır. Bu parça çıktıyı **küme** haline
getirir ve **küme bazlı onayı** akışa bağlar (Belge Bölüm 7): "şu 12 yazım muhtemelen aynı
ürün" grubu kullanıcıya sunulur; kullanıcı onaylar/böler. Yüksek güvenli kümeler otomatik
birleşir. Sonra Transformer/Writer entity sonucunu kullanır.

## 1. Amaç
- Eşleşme kararlarını **kümelere** dönüştür (bağlı bileşenler / union-find).
- Kümeleri kullanıcı onayına sunulacak biçimde raporla (rapor + düzenlenebilir dosya).
- Onaylı kümeleri Transformer/Writer'a bağla: birleşik veride tekilleştirme uygulansın,
  belirsiz kalanlar `merge_report`'a düşsün.

## 2. Oluşturulacak / Değiştirilecek Dosyalar
```
core/entity.py        # cluster() + küme raporu üretimi (4a/4b'ye ekle)
core/transformer.py   # onaylı kümeleri tekilleştirmede kullan
core/writer.py        # merge_report'a "entity belirsizleri" bölümünü doldur
cli/main.py           # entity küme onayı akışı (analyze çıktısına/ayrı dosyaya)
tests/test_entity_cluster.py
tests/test_entity_e2e.py
```

## 3. Gereksinimler
- Kümeleme: eşleşme kararlarından bağlı bileşenler; her kümeye temsilci (canonical) değer.
- **Yüksek güvenli kümeler otomatik birleşir**; belirsiz/gri kümeler kullanıcı onayına
  (düzenlenebilir bir küme dosyası veya mapping benzeri yapı) sunulur — HITL korunur.
- Onaylanmadan belirsiz küme birleştirilmez (kör tekilleştirme yok).
- `merge_report`: entity'de belirsiz kalan ürünler listelenir (Belge Bölüm 5).
- Ölçek: kümeleme blok bazlı sonuçlar üzerinden; genel patlama yok.

## 4. Değişmez Kısıtlar (Belge Bölüm 14)
- Belirsiz kümeler kullanıcı onayı olmadan birleşmez (HITL).
- LLM satır verisini işlemez; tekilleştirmeyi deterministik kod uygular.
- Provenance korunur — tekilleştirilen satırların kökeni izlenebilir kalır.
- Sadece dikey birleştirme.

## 5. Testler
- [ ] Varyant grubu tek kümeye toplanıyor; canonical değer seçiliyor.
- [ ] Yüksek güvenli küme otomatik; belirsiz küme onaysız birleşmiyor.
- [ ] Onaylı kümeler Transformer'da tekilleştirmeye yansıyor (satır sayısı beklenen).
- [ ] `merge_report` entity belirsizlerini listeliyor.
- [ ] E2E: analyze → mapping onayı → entity küme onayı → apply → tekilleştirilmiş çıktı.

## 6. Kabul Kriterleri
1. [ ] Eşleşmeler kümelere dönüşür; canonical + üyeler net.
2. [ ] Küme bazlı onay akışı çalışır; belirsizler onaysız birleşmez.
3. [ ] Transformer/Writer onaylı kümeleri kullanır; `merge_report` belirsizleri gösterir.
4. [ ] E2E test geçer; `pytest` yeşil. **Aşama 4 (Entity Resolution) tamamlanır.**

## 7. Önceki Aşama Doğrulama Kontrol Listesi (Aşama 4b)
- [ ] Embedding + iki eşik ile aynı/farklı/gri karar çalışıyor mu?
- [ ] Yalnızca gri bölge LLM'e gidiyor; oran küçük mü?
- [ ] Belirsizler otomatik birleşmiyor mu?
- [ ] Gerçek API çağrısı yok, `pytest` yeşil mi?

Eksik varsa önce gider, kısa rapor yaz, sonra 4c'ye başla.

## 8. Teslim
Küme raporu örneği, tekilleştirilmiş E2E çıktısı, `pytest` çıktısı, kabul kriterleri ✓/✗.
