# Multimedia Master — Tabella di test

Checklist di collaudo manuale per garantire la piena funzionalità prima di
una distribuzione. Eseguire **sul PC Windows di destinazione** (è lì che si
manifestano i problemi di console, ffmpeg e PyInstaller).

**Legenda esito:** ✅ ok · ⚠️ funziona con riserve · ❌ rotto · ⏭️ saltato (dip. opzionale assente)

**Dipendenze opzionali** (i test relativi sono ⏭️ se assenti, non ❌):
`pymupdf` (editor PDF) · `tkinterdnd2` (drag & drop) · `demucs` + PyTorch (separazione stem, solo Audio Manager)

**Setup ambiente:** eseguire `setup.bat` (Windows) una volta — crea `venv` e installa tutto (core + opzionali + PyInstaller). Poi `build.bat` attiva il venv da solo.

**Due prodotti, una sola build:** `build.bat` produce la suite completa (`dist\MultimediaMaster\`), `build-pdf.bat` il solo Gestione PDF come prodotto a sé (`dist\PdfManager\`). Entrambi usano lo stesso `MultimediaMaster.spec`, così l'elenco delle dipendenze resta in un posto solo.

---

## 0. Build & avvio (packaging)

| ID | Test | Passi | Risultato atteso | Esito |
|----|------|-------|------------------|:----:|
| B0 | Setup ambiente | Eseguire `setup.bat` una volta | Crea `venv` e installa requirements core + opzionali + PyInstaller, nessun errore | ☐ |
| B0b | Smoke test | `python smoke_test.py` (nel venv) | `RESULT: OK` — verifica versioni di sicurezza (Pillow/pypdf), import e i percorsi pypdf (merge/split/cifra/decifra) | ☐ |
| B0c | Audit dipendenze | `pip-audit -r requirements.txt -r requirements-optional.txt` | Solo `stanza` (CVE-2026-54499, rischio residuo documentato e non raggiungibile); tutto il resto pulito | ☐ |
| B1 | Build exe | Eseguire `build.bat` (attiva `venv` da solo se presente) | Nessun errore; creato `dist\MultimediaMaster\MultimediaMaster.exe` | ☐ |
| B2 | Avvio launcher | Doppio click sull'exe | Si apre la finestra launcher con 3 card | ☐ |
| B3 | Nessuna console | Avvio dell'exe | NON deve apparire nessuna finestra console nera | ☐ |
| B4 | Avvio tool da exe | Click su ogni card | Ogni tool si apre come finestra separata | ☐ |
| B5 | Log di crash scrivibili | Provocare un errore o controllare dopo l'uso | I log finiscono in `logs\<tool>_crash.log` accanto all'exe (o in `%TEMP%\MultimediaMaster\logs` se installato in cartella protetta) | ☐ |
| B6 | Avvio da sorgente | `python launcher.py` | Identico comportamento alla versione compilata | ☐ |

### 0b. Build separata del solo PDF Manager

Prodotto a sé, senza launcher e senza convertitore immagini / audio manager.
Si costruisce dallo stesso `MultimediaMaster.spec` (variabili `MM_TARGET` e
`MM_ONEFILE`).

| Comando | Risultato | Avvio |
|---|---|---|
| `build-pdf.bat` | `dist\PdfManager.exe` — **un solo file**, da trascinare ovunque | lento (si scompatta ogni volta) |
| `build.bat pdf` | `dist\PdfManager\` — cartella + zip | istantaneo |

| ID | Test | Passi | Risultato atteso | Esito |
|----|------|-------|------------------|:----:|
| P1 | Build file unico | Eseguire `build-pdf.bat` | Nessun errore; creato `dist\PdfManager.exe`, **nessuna cartella** `dist\PdfManager\` | ☐ |
| P1b | Davvero autonomo | Copiare **solo** `PdfManager.exe` sul desktop di un PC pulito, cancellare `dist` | Parte e funziona senza nessun altro file accanto | ☐ |
| P1c | Attesa all'avvio | Cronometrare il doppio click | Qualche secondo prima che compaia la finestra, **a ogni avvio** — è il prezzo del file unico, non un difetto | ☐ |
| P1d | Build a cartella | Eseguire `build.bat pdf` | Creato `dist\PdfManager\PdfManager.exe` + zip; avvio istantaneo | ☐ |
| P2 | Avvio diretto | Doppio click sull'exe | Si apre **direttamente** Gestione PDF — nessuna finestra launcher, nessuna console | ☐ |
| P2b | Icona della finestra | Guardare l'angolo della finestra e la barra applicazioni | Compare l'icona del programma, non quella generica di Windows (valeva anche per la suite: era rotta in silenzio) | ☐ |
| P3 | Titolo finestra | Guardare la barra del titolo | Dice solo `Gestione PDF` | ☐ |
| P4 | Finestra Informazioni | Click sulla ⓘ in alto a destra | Dice `PDF Manager` + versione | ☐ |
| P5 | Funzioni PDF complete | Provare ogni scheda (modifica, converti, unisci, dividi, proteggi, analizza) | Tutto funziona come nella suite completa | ☐ |
| P6 | Sei schede, non sette | Guardare la barra delle schede | **Nessuna scheda "Traduci"** | ☐ |
| P7 | Niente audio | Ispezionare `dist\PdfManager\` | Nessun `ffmpeg.exe`, nessun `scipy`/`pydub`/`soundfile`; cartella sensibilmente più piccola di `dist\MultimediaMaster\` | ☐ |

**Nessuna traccia degli altri strumenti** — il cliente che compra solo questo
non deve trovare da nessuna parte il nome della suite né i tool che non ha
acquistato. Verifiche mirate:

| ID | Test | Passi | Risultato atteso | Esito |
|----|------|-------|------------------|:----:|
| P8 | Ricerca testuale | In PowerShell, dentro `dist\PdfManager`: `Get-ChildItem -Recurse -File \| Select-String -Pattern "multimedia","image_converter","audio_manager" -List` | **Nessun risultato** | ☐ |
| P9 | Cartella impostazioni | Usare l'app, poi guardare in `C:\Users\<nome>` | Esiste `.pdf_manager\settings.json` — **non** `.multimedia_master` | ☐ |
| P10 | Log di crash (file unico) | Provocare un errore | Log in `C:\Users\<nome>\.pdf_manager\logs\` — e **nessuna cartella `logs`** creata accanto all'exe, che sporcherebbe il desktop | ☐ |
| P10b | Log di crash (cartella) | Idem sulla build `build.bat pdf` | Log in `logs\` accanto all'exe, come nella suite | ☐ |
| P11 | Notifica desktop | Far finire un lavoro lungo con la finestra in secondo piano | Il toast di Windows è attribuito a `PDF Manager` | ☐ |
| P12 | Niente file da sviluppatore | Ispezionare `dist\PdfManager\` | Nessun `assets\generate_icon.py` | ☐ |

| ID | Test | Passi | Risultato atteso | Esito |
|----|------|-------|------------------|:----:|
| P13 | Suite non regredita | Rifare `build.bat` dopo `build-pdf.bat` | Si costruisce e funziona come prima; titolo e Informazioni dicono ancora `Multimedia Master`; le impostazioni restano in `.multimedia_master` (nessuno perde le preferenze salvate) | ☐ |
| P14 | Chiavi di licenza | Se sono già state emesse chiavi per la suite, riprovarne una | Continua a essere valida (il "sale" della suite non è cambiato). Una chiave della suite **non** deve attivare il PDF Manager e viceversa | ☐ |

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
