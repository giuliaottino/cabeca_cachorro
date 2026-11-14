# Expedições em 3D (protótipo)

Animação 3D dos trajetos de GPS das expedições sobre relevo e satélite, em PT/EN.
Abra `index.html` direto no navegador (não precisa de servidor). O idioma segue o
site (`?lang=en` ou a escolha salva em `tsiino-language`).

## Adicionar uma expedição ou trilha (ex.: Morro Opota, Maturacá)

1. Coloque o KML em `_input_data/kml_expedições/` (ex.: `morro-opota-subida.kml`).
2. Coloque as fotos em `_input_data/expedicoes_fotos/<pasta>/`.
3. Edite `_input_data/expedicoes_3d.json`:

   ```json
   {
     "id": "maturaca-2026",
     "name": "Morro Opota",
     "name_en": "Opota Hill",
     "region": "Maturacá",
     "date": "2026-11",
     "photos": "maturaca-2026",
     "trails": [
       { "kml": "comunidade-ate-base-do-opota", "name": "Comunidade → base do Opota", "name_en": "Village → Opota base" },
       { "kml": "morro-opota-subida", "name": "Subida do Opota", "name_en": "Opota ascent" }
     ]
   }
   ```

4. Rode na raiz do repositório:

   ```bash
   python prototipos/expedicoes-3d/build_data.py
   ```

A ordem das trilhas no JSON é a ordem da viagem. O sentido de cada linha é
ajustado automaticamente para começar perto de onde a anterior terminou.

## Tipos de trajeto e câmera

| `mode`   | Detecção automática                        | Câmera |
|----------|--------------------------------------------|--------|
| `rio`    | trajeto > 15 km                            | alta, segue a direção do barco |
| `trilha` | demais                                     | atrás do caminhante; se afasta sozinha quando o terreno atrás dela sobe |
| `subida` | desnível ≥ 250 m na altitude do GPS. Sem altitude no KML, mede no relevo durante a visão geral | de lado e afastada, rumo quase fixo, no lado de terreno mais baixo; relevo menos exagerado; marca o cume |

Para forçar um tipo, use `"mode": "subida"` na trilha. Os limites ficam em
`RIVER_MIN_M` e `CLIMB_MIN_RELIEF` em `build_data.py`.

## Legendas e posição das fotos (opcional)

Crie `legendas.csv` dentro da pasta de fotos (vírgula ou ponto e vírgula):

```csv
arquivo,legenda_pt,legenda_en,credito,trajeto,lat,lon
IMG_4182.jpg,Mabea sp. na terra firme,Mabea sp. in terra firme forest,Foto: Fulano,,,
IMG_4191.jpg,Subida da Mão da Bela,Climbing the Bela's Hand,,trilha-mao-da-bela-adormecida,,
IMG_4264.jpg,Vista do cume,View from the summit,,,-0.3258,-66.8290
```

- Sem `lat`/`lon`: a foto viaja junto, num cartão preso ao ponto que percorre o
  trajeto (não se afirma onde ela foi tirada). Com `trajeto`, ela só passa
  enquanto aquele trajeto anima; sem nada, entra no rodízio geral.
- Com `lat`/`lon`: a foto fica presa no lugar exato, aparece quando a linha
  chega e depois vira um ponto clicável no mapa.
- Clicar em qualquer foto abre a galeria em tela cheia (setas e Esc).

Os waypoints com nome dentro dos KMLs aparecem como "Registro de campo".
Revise os nomes antes de publicar (alguns são anotações de campo).
