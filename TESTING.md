# Multimedia Master — Tabella di test

Checklist di collaudo manuale per garantire la piena funzionalità prima di
una distribuzione. Eseguire **sul PC Windows di destinazione** (è lì che si
manifestano i problemi di console, ffmpeg e PyInstaller).

**Legenda esito:** ✅ ok · ⚠️ funziona con riserve · ❌ rotto · ⏭️ saltato (dip. opzionale assente)

**Dipendenze opzionali** (i test relativi sono ⏭️ se assenti, non ❌):
`pymupdf` (editor PDF) · `rapidocr-onnxruntime` (OCR) · `demucs` + PyTorch (separazione stem) · `tkinterdnd2` (drag & drop) · `argostranslate` (traduzione PDF, + download lingue al primo uso) · `wordninja` (de-incollaggio parole OCR prima della traduzione) · `pyspellchecker` (correzione refusi OCR a un carattere) · `transformers`+`torch` (motori traduzione NLLB-200 / mBART-50, modello ~2.4 GB scaricato al primo uso)

**Setup ambiente:** eseguire `setup.bat` (Windows) una volta — crea `venv` e installa tutto (core + opzionali + PyInstaller). Poi `build.bat` attiva il venv da solo.

---

## 0. Build & avvio (packaging)

| ID | Test | Passi | Risultato atteso | Esito |
|----|------|-------|------------------|:----:|
| B0 | Setup ambiente | Eseguire `setup.bat` una volta | Crea `venv` e installa requirements core + opzionali + PyInstaller, nessun errore | ☐ |
| B0b | Smoke test | `python smoke_test.py` (nel venv) | `RESULT: OK` — verifica versioni di sicurezza (Pillow/pypdf), import, i percorsi pypdf (merge/split/cifra/decifra) e la pulizia testo traduzione | ☐ |
| B0c | Audit dipendenze | `pip-audit -r requirements.txt -r requirements-optional.txt` | Solo `stanza` (CVE-2026-54499, rischio residuo documentato e non raggiungibile); tutto il resto pulito | ☐ |
| B1 | Build exe | Eseguire `build.bat` (attiva `venv` da solo se presente) | Nessun errore; creato `dist\MultimediaMaster\MultimediaMaster.exe` | ☐ |
| B2 | Avvio launcher | Doppio click sull'exe | Si apre la finestra launcher con 3 card | ☐ |
| B3 | Nessuna console | Avvio dell'exe | NON deve apparire nessuna finestra console nera | ☐ |
| B4 | Avvio tool da exe | Click su ogni card | Ogni tool si apre come finestra separata | ☐ |
| B5 | Log di crash scrivibili | Provocare un errore o controllare dopo l'uso | I log finiscono in `logs\<tool>_crash.log` accanto all'exe (o in `%TEMP%\MultimediaMaster\logs` se installato in cartella protetta) | ☐ |
| B6 | Avvio da sorgente | `python launcher.py` | Identico comportamento alla versione compilata | ☐ |

---

## 1. Launcher

| ID | Test | Passi | Risultato atteso | Esito |
|----|------|-------|------------------|:----:|
| L1 | Layout | Aprire il launcher | 3 card affiancate, uguali, testo leggibile | ☐ |
| L2 | **Resize piccolo** (bug storico) | Rimpicciolire la finestra al minimo | Le card si ridimensionano in scala, **nessun loop/crash watchdog**, nessuna CPU al 100% | ☐ |
| L3 | Resize grande / fullscreen | Massimizzare | Layout stabile, card centrate | ☐ |
| L4 | Lancio processi | Click su ognuna delle 3 card | Ogni tool parte come processo indipendente | ☐ |
| L5 | Isolamento | Aprire un tool, poi chiudere il launcher | Il tool resta aperto e funzionante | ☐ |
| L6 | Crash precoce | (se un tool è rotto) parte e muore < 2s | Il launcher mostra dialog "Strumento terminato" con percorso log | ☐ |

---

## 2. Convertitore Immagini

| ID | Test | Passi | Risultato atteso | Esito |
|----|------|-------|------------------|:----:|
| I1 | Aggiunta file (pulsante) | Aggiungere immagini via dialog | Compaiono nella lista | ☐ |
| I2 | Drag & drop | Trascinare immagini nella finestra | Vengono aggiunte (⏭️ se manca tkinterdnd2) | ☐ |
| I3 | Conversione JPG | Selezionare JPG, convertire | File `.jpg` creati, anteprima aggiornata | ☐ |
| I4 | Conversione PNG | Formato PNG | File `.png` corretti | ☐ |
| I5 | Conversione WebP | Formato WebP | File `.webp` corretti | ☐ |
| I6 | Conversione AVIF | Formato AVIF | File `.avif` corretti (o errore chiaro se plugin assente) | ☐ |
| I7 | Qualità | Variare lo slider qualità | Dimensione output cambia coerentemente | ☐ |
| I8 | Ridimensiona | Impostare larghezza/altezza target | Immagini ridimensionate | ☐ |
| I9 | Stima dimensioni | Cambiare impostazioni con file in lista | Stima aggiornata dopo ~0.8s, senza freeze | ☐ |
| I10 | Pulizia metadati | Usare "Pulisci" | File `_clean` senza EXIF; riepilogo metadati rimossi | ☐ |
| I11 | Avviso animati | Convertire GIF/WebP animato in formato statico | Dialog di avviso "solo primo fotogramma" | ☐ |
| I12 | Annulla batch | Avviare batch grande, premere Annulla | Si ferma dopo il file corrente, stato "Annullato" | ☐ |
| I13 | Notifica fine | Batch ≥ 3 file | Notifica desktop a fine lavoro, **senza flash console** | ☐ |
| I14 | Anteprima | Selezionare un file convertito | Mostra confronto sorgente/risultato | ☐ |

---

## 3. Gestione PDF

| ID | Test | Passi | Risultato atteso | Esito |
|----|------|-------|------------------|:----:|
| P0 | Avvio rapido | Apri la finestra "Gestione PDF" | Si apre rapidamente: solo la scheda "Modifica" viene costruita subito, le altre 6 vengono costruite al primo click (nessun ritardo percepibile nel cambio scheda) | ☐ |

### 3a. Modifica (editor visuale — richiede pymupdf)

| ID | Test | Passi | Risultato atteso | Esito |
|----|------|-------|------------------|:----:|
| P1 | Apri PDF | "Apri PDF" e scegliere un file | Pagina renderizzata su canvas (⏭️ se manca pymupdf → messaggio chiaro) | ☐ |
| P2 | Navigazione | Frecce ◀ ▶ e tasti PgUp/PgDn | Cambia pagina, label "n / tot" aggiornata | ☐ |
| P3 | Zoom | Menu zoom 50–200% | Render riscalato | ☐ |
| P4 | Ritaglia (snip) | Modalità ✂, disegnare rettangolo | Blocco ritagliato/spostabile | ☐ |
| P5 | Sposta (drag) | Modalità ✥, trascinare blocco | Blocco si muove | ☐ |
| P6 | Spazio (space) | Modalità ↕, trascinare su/giù | Aggiunge/rimuove spazio bianco | ☐ |
| P7 | **Annulla (Ctrl+Z)** | Fare una modifica, premere Ctrl+Z | Modifica annullata (verifica fix bind_all: **nessun crash all'avvio**) | ☐ |
| P8 | Salva (Ctrl+S) | Salvare il PDF modificato | File `_modificato.pdf` corretto | ☐ |

### 3b. Altre schede

| ID | Test | Passi | Risultato atteso | Esito |
|----|------|-------|------------------|:----:|
| P9  | Converti immagini→PDF | Aggiungere immagini, generare PDF | PDF multi-pagina creato | ☐ |
| P10 | OCR | Attivare OCR in conversione | PDF ricercabile (⏭️ se manca rapidocr-onnxruntime → messaggio chiaro) | ☐ |
| P11 | Unisci | Aggiungere più PDF, unire | PDF unico nell'ordine scelto | ☐ |
| P12 | Drag&drop PDF | Trascinare PDF nella scheda Unisci | Aggiunti alla lista | ☐ |
| P13 | Dividi per range | Es. "1-3,5" | File con le pagine indicate | ☐ |
| P14 | Dividi ogni N | Ogni N pagine | File spezzati correttamente | ☐ |
| P15 | Proteggi (cifra) | Impostare password | PDF cifrato, richiede password all'apertura | ☐ |
| P16 | Proteggi (decifra) | Rimuovere password da PDF cifrato | PDF apribile senza password | ☐ |
| P17 | Analizza | Aprire un PDF | Testo, metadati, campi modulo, sintesi mostrati | ☐ |
| P45 | **Permessi di protezione** | Proteggi: togliere **entrambe** le spunte (stampa e copia), cifrare, poi aprire il PDF e provare a stampare/copiare | Stampa e copia **bloccate** (prima toglierle le concedeva tutte); con "Consenti stampa" spuntata la stampa funziona | ☐ |
| P46 | **Un PDF per immagine — sovrascrittura** | In una cartella con `foto.pdf` già esistente, convertire `foto.jpg` in modalità "Un PDF per immagine" | Viene creato `foto (1).pdf`; il `foto.pdf` esistente **non viene toccato** | ☐ |
| P47 | **Drag&drop con spazi nel percorso** | Trascinare un file da una cartella con spazi nel nome (es. `Nuova cartella\Scansione 1.pdf`) | Il file viene aggiunto (prima il drop veniva ignorato in silenzio) | ☐ |
| P48 | **Doppio click su Proteggi** | Selezionare un PDF grande, inserire password e cliccare "Proteggi PDF" due volte rapidamente | La seconda pressione è ignorata, i pulsanti si disabilitano fino alla fine; nessun PDF troncato | ☐ |
| P49 | **Ritaglia sopra un ritaglio** | Modifica: ritagliare un blocco, spostarlo, poi ritagliare una regione che lo contiene e spostare il nuovo blocco | Sotto **non resta una copia** del primo blocco | ☐ |
| P50 | **Selezione oltre il bordo** | Modifica: a zoom 50%, trascinare la selezione oltre il bordo della pagina nell'area grigia, poi Ritaglia | Nessuna **banda nera** nel blocco ritagliato né nel PDF salvato | ☐ |
| P51 | **Selezione e cambio pagina** | Modifica: disegnare una selezione, poi premere PgDn (o ▶) **senza** scegliere, poi cliccare Ritaglia | Il pannello di scelta sparisce al cambio pagina; non viene ritagliato nulla sulla pagina nuova. Idem cambiando zoom | ☐ |

### 3c. Traduci (in-place, offline — richiede argostranslate)

| ID | Test | Passi | Risultato atteso | Esito |
|----|------|-------|------------------|:----:|
| P18 | Dipendenza assente | Avviare senza argostranslate installato | Messaggio chiaro nella scheda, nessun crash (⏭️) | ☐ |
| P19 | Nessuna lingua installata | Prima apertura, nessun pacchetto lingua scaricato | Messaggio "nessuna lingua installata", pulsanti traduzione disabilitati | ☐ |
| P20 | Scarica coppia lingue | "Gestisci lingue" → Aggiorna elenco → Scarica e installa | Pacchetto scaricato, comparso tra le lingue installate | ☐ |
| P21 | Traduci PDF testuale | Selezionare PDF con testo digitale, scegliere lingue, Traduci | PDF tradotto con stesso layout, testo sostituito, font ridotto se necessario per restare nel riquadro originale | ☐ |
| P22 | Traduci PDF scansionato | Selezionare PDF scansionato con OCR attivo | Testo riconosciuto via OCR e sostituito nella stessa posizione (⏭️ se manca rapidocr-onnxruntime) | ☐ |
| P23 | Glossario | Aggiungere un termine con traduzione forzata, tradurre un PDF che lo contiene | Il termine appare tradotto come specificato nel glossario | ☐ |
| P24 | Annulla traduzione | Avviare la traduzione di un PDF lungo, premere Annulla | Si ferma dopo la pagina corrente; le pagine già tradotte restano tradotte | ☐ |
| P25 | Pagine senza testo | Tradurre un PDF con pagine puramente grafiche (no testo, OCR disattivato) | Quelle pagine restano invariate, nessun errore | ☐ |
| P26 | Revisione manuale — rimozione | Spuntare "Revisione manuale", tradurre, rimuovere (✕) una sezione nella prima finestra di revisione | Nel PDF finale quella sezione resta identica all'originale (non tradotta, non redatta) | ☐ |
| P27 | Revisione manuale — editing testo estratto | Spuntare "Revisione manuale", correggere il testo di una sezione nella prima finestra prima di continuare | La traduzione successiva usa il testo corretto, non quello estratto originariamente | ☐ |
| P28 | Revisione manuale — editing traduzione | Spuntare "Revisione manuale", correggere il testo tradotto nella seconda finestra di revisione | Il PDF finale contiene il testo corretto a mano, non quello prodotto dal motore MT | ☐ |
| P29 | Revisione manuale — annulla a metà | Spuntare "Revisione manuale", premere "Annulla traduzione" in una delle due finestre di revisione | Nessun PDF viene generato, stato torna a pronto | ☐ |
| P30 | Motore NLLB-200 — selezione | Selezionare "NLLB-200" nel menu Motore | Le lingue compaiono subito (tabella statica, **nessun** download avviato); "Gestisci lingue" disabilitato; nota sul modello ~2.4 GB | ☐ |
| P31 | Motore NLLB-200 — traduzione | Con transformers+torch installati, tradurre un PDF (en→it) con NLLB-200 | Modello scaricato una volta al primo uso, poi offline; traduzione più naturale/contestuale di Argos; paragrafi lunghi non troncati | ☐ |
| P32 | Motore assente | Selezionare NLLB-200 o mBART-50 senza transformers/torch installati | Messaggio "non disponibile" con hint pip, nessun crash, nessuna lingua elencata (⏭️) | ☐ |
| P33 | Correzione OCR | Tradurre/estrarre testo OCR con refusi a un carattere (es. "1n") con revisione manuale | Nella finestra di revisione "1n" appare già corretto in "In"; sigle/codici (BCS, 12V) restano invariati (⏭️ se manca pyspellchecker) | ☐ |
| P34 | **Correzione manuale rispettata** | Nella revisione del testo estratto, riscrivere a mano una parola che la pulizia automatica aveva spezzato (es. un codice `POWERUNITS` diventato `POWER UNITS`), poi tradurre | Il PDF finale contiene **la tua versione**, non quella rispezzata dall'algoritmo | ☐ |
| P35 | **Paragrafo lungo con mBART** | Tradurre un PDF con un paragrafo molto lungo (>400 parole) usando mBART-50 | Il paragrafo è tradotto **per intero**; prima la coda veniva persa in silenzio | ☐ |
| P36 | Blocco senza punteggiatura | Tradurre una pagina con elenchi puntati / celle di tabella lunghe senza punto finale (NLLB o mBART) | Nessun troncamento: tutto il contenuto arriva tradotto | ☐ |
| P37 | Glossario con termini annidati | In "Glossario" aggiungere sia `power`→`potenza` sia `power unit`→`gruppo motore`, poi tradurre un testo che contiene "power unit" | Esce **"gruppo motore"** (vince il termine più lungo), non "potenza unit" | ☐ |
| P38 | **Testo che non entra** | Tradurre EN→DE (o EN→IT) un PDF con etichette brevi in tabelle/schemi (es. "Speed") | Nessuna etichetta **sparisce**: dove la traduzione non entra resta il testo originale, e a fine lavoro compare l'avviso "N sezione/i non tradotta/e… non entrava" | ☐ |
| P39 | **Annulla subito** | Avviare una traduzione e premere Annulla entro 1-2 secondi (prima che traduca qualcosa) | Messaggio "Annullato prima che venisse tradotto qualcosa: nessun file è stato creato"; **nessun PDF di output** viene scritto (prima ne creava una copia non tradotta annunciata come "N pagine tradotte") | ☐ |
| P40 | **Fallimenti parziali segnalati** | Tradurre con NLLB/mBART su una macchina con poca RAM, così alcune sezioni falliscono | Il risultato riporta "N sezione/i su M non tradotta/e, lasciata/e nella lingua originale" — non più successo pulito | ☐ |
| P41 | OCR fallito su una pagina | Tradurre un PDF scansionato con una pagina enorme (poster/schema piegato) che manda l'OCR in errore | Avviso "N pagina/e scansionata/e non riconosciuta/e (OCR fallito)"; prima la pagina passava per "pagina senza testo" | ☐ |
| P42 | **Frecce nella revisione** | Nella revisione manuale, cliccare in una casella di testo e premere ← / → | Il cursore si sposta **dentro il testo** e la pagina **non cambia**; PgUp/PgDn cambiano pagina | ☐ |
| P43 | **Annulla (Ctrl+Z) nella revisione** | Andare a pagina 2, modificare una sezione, premere Ctrl+Z molte volte (più delle modifiche fatte) | Si annullano solo le **proprie** modifiche; non compare mai il testo di una sezione di un'altra pagina | ☐ |
| P44 | mBART offline | Con transformers/torch installati ma modello mai scaricato, e **connessione disattivata**, selezionare mBART-50 dal menu Motore | Le lingue compaiono subito (52), **nessun tentativo di rete**, nessun errore | ☐ |

---

## 4. Audio Manager

| ID | Test | Passi | Risultato atteso | Esito |
|----|------|-------|------------------|:----:|
| A1  | Avviso dipendenze | Avviare senza una dip. core | Striscia gialla con `pip install ...` | ☐ |
| A2  | ffmpeg assente | (se ffmpeg/imageio-ffmpeg manca) provare conversione/play | Messaggio chiaro "pip install imageio-ffmpeg", **nessun crash** | ☐ |
| A3  | Converti | Batch conversione formato | File convertiti, **nessun flash console** per ogni file | ☐ |
| A4  | Estrai da video | Caricare un video | Traccia audio estratta | ☐ |
| A5  | Pulisci | WAV → MP3 web | MP3 ottimizzato creato | ☐ |
| A6  | Migliora | Riduzione rumore + normalizza | Audio più pulito (⏭️ noisereduce/scipy se assenti) | ☐ |
| A7  | Modifica — waveform | Caricare audio | Forma d'onda visualizzata | ☐ |
| A8  | Modifica — play | Premere play | Riproduzione (⏭️ se manca sounddevice → messaggio chiaro) | ☐ |
| A9  | Modifica — anteprima effetto | Cambiare EQ/volume/velocità, anteprima 6s | Clip riprodotta con effetto, **nessun flash console** | ☐ |
| A10 | Modifica — trim/fade/split | Applicare e salvare | File risultante corretto | ☐ |
| A11 | Separa stem | Avviare separazione | Stem separati (⏭️ se manca demucs/torch → messaggio chiaro, no crash) | ☐ |
| A12 | Metadati — leggi | Caricare file con tag | Tag mostrati | ☐ |
| A13 | Metadati — scrivi | Modificare e salvare tag + copertina | Tag persistiti | ☐ |
| A14 | **Metadati — selezione rapida** | Caricare un file grande (>200 MB) e uno piccolo; cliccare il grande e **subito** il piccolo; attendere; premere Salva | I campi mostrati restano quelli del file piccolo (il caricamento lento viene scartato); Salva scrive sul file **selezionato**, non su quello caricato per primo | ☐ |
| A15 | **Metadati — rimuovi dalla lista** | Aggiungere 4 file, selezionare il 2°, "Rimuovi", poi cliccare le righe rimaste | Ogni riga seleziona il **proprio** file; l'ultima resta cliccabile; "Wipe sel." agisce sul file evidenziato | ☐ |
| A16 | **Effetti voce a 48 kHz** | Convertire un file in Opus (o usare audio estratto da video), poi applicare un effetto voce (es. "Malvagia") | Durata **invariata** rispetto all'originale e intonazione corretta (prima si allungava di ~9% a 48 kHz e raddoppiava a 96 kHz) | ☐ |
| A17 | **Modifica su .m4a** | Aprire un .m4a (memo vocale iPhone), fare trim/fade/muta/dividi | Operazioni completate e file scritto (prima fallivano tutte con errore ffmpeg sul formato) | ☐ |
| A18 | Conversione — lista bloccata | Avviare un batch e provare Aggiungi/Rimuovi/Pulisci | I pulsanti rispondono "Conversione in corso"; conteggio e progresso restano coerenti | ☐ |
| A19 | Modifica — cambio file durante il caricamento | Caricare un file lungo e cambiarne subito un altro | Durata/info mostrate sono quelle del **nuovo** file; "Applica" taglia sui tempi giusti | ☐ |

---

## 5. Trasversali (robustezza)

| ID | Test | Passi | Risultato atteso | Esito |
|----|------|-------|------------------|:----:|
| X1 | Crash fatale → dialog | Forzare un errore all'avvio di un tool | Compare dialog "errore irreversibile" con percorso log; niente sparizione silenziosa | ☐ |
| X2 | Nessun flash console (globale) | Usare ogni operazione ffmpeg + notifica | Mai una finestra console nera su Windows | ☐ |
| X3 | Persistenza impostazioni | Cambiare impostazioni, riavviare | Impostazioni ricordate | ☐ |
| X4 | File con caratteri speciali | Usare file con spazi/accenti/unicode nel nome | Funziona senza errori | ☐ |
| X5 | Percorso file inesistente | Rimuovere un file dopo averlo aggiunto, poi elaborare | Errore gestito, non crash | ☐ |

---

## 6. Licenza (quando attivata in vendita)

> Non collegata all'avvio finché è in uso personale. Test da eseguire quando si abilita il gating.

| ID | Test | Passi | Risultato atteso | Esito |
|----|------|-------|------------------|:----:|
| K1 | Genera chiave | `python -m common.license generate "cliente@email.com"` | Stampa una chiave `SLUG-CHECKSUM` | ☐ |
| K2 | Attiva valida | Inserire la chiave generata | `activate()` ritorna True, chiave salvata | ☐ |
| K3 | Rifiuta non valida | Inserire chiave alterata/inventata | `activate()` ritorna False, nessun salvataggio | ☐ |
| K4 | Persistenza attivazione | Riavviare dopo attivazione | `is_activated()` resta True | ☐ |
