# trumpsvetoes.com

A satirical running counter of President Trump's formal vetoes since November 4, 2026,
plus a separate tally of veto threats. A small script checks official sources once a day.

## Wat zit erin

| Map / bestand | Wat het doet |
|---|---|
| `docs/index.html` | De hele website (één bestand). Pas bovenin het `<script>` je Ko-fi-link aan. |
| `docs/data.json` | De cijfers die de site toont. Wordt dagelijks automatisch ververst. |
| `docs/CNAME` | Vertelt GitHub Pages dat de site op trumpsvetoes.com draait. |
| `docs/fonts/` | Lettertype Anton (SIL Open Font License), zelf gehost, dus geen Google-verzoeken. |
| `scripts/update_data.py` | Het dagelijkse script. |
| `scripts/manual.json` | Handmatig dingen verbergen of toevoegen (bijv. een foute dreiging). |
| `.github/workflows/update.yml` | Laat GitHub het script elke dag om 06:17 UTC draaien. |
| `tests/test_parsers.py` | Controleert dat het script de bronpagina's nog goed leest. |

## Wat wordt geteld

- **Formele vetoes**: alles op de officiële lijst van de Amerikaanse Senaat, vanaf 4 november 2026 (inclusief pocket vetoes).
- **Dreigementen** (geteld): berichten van Trump zelf via het archief trumpstruth.org, mits er een duidelijke dreigtaal in staat ("I will veto ...", "Mr. Veto").
- **Nieuws** (niet geteld): koppen van grote media, via een strikt filter.

## Lokaal bekijken

    cd docs
    python3 -m http.server 8000
    # open http://localhost:8000
    # voorbeeld van de stempelanimatie: http://localhost:8000/?demo=3

## Script lokaal proberen

    pip install -r scripts/requirements.txt
    python tests/test_parsers.py
    python scripts/update_data.py --dry-run

## Belangrijk om te weten

- De bronpagina's (Senaat, trumpstruth.org) kunnen van opbouw veranderen. Het script geeft dan een foutmelding in plaats van stilletjes verkeerde cijfers te tonen, en GitHub mailt je dat de taak is mislukt.
- Controleer de eerste paar dagen de logregel `NEW THREAT` in het Actions-logboek, om te zien of het dreigingsfilter niets verkeerds oppakt. Een fout-positief verberg je door de bronlink in `scripts/manual.json` bij `hide_urls` te zetten.
- Lees de voorwaarden van trumpstruth.org en vermeld de bron (dat staat al in de voettekst).
