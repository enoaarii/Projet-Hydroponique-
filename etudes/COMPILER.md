# Compiler les études

Les trois études sont des documents LaTeX (pdflatex, babel french).

## Figures

Les figures des études électrique et hydraulique ne sont pas versionnées :
elles sont produites par les scripts, à lancer avant la compilation.

```bash
cd etudes/electrique && python3 modele_panneau.py && python3 calculs.py
cd etudes/hydraulique && python3 calculs.py
```

Dépendances : numpy, scipy, matplotlib.

L'étude électrique attend aussi, dans `protocole/`, les deux images produites par
`traitement_mesures.py` (`exemple_bilan_journee.png` et `exemple_ecarts.png`) :

```bash
cd etudes/electrique && python3 traitement_mesures.py
```

## Compilation

```bash
pdflatex Etude_electrique_v2.tex   # deux fois, pour la table des matières
pdflatex Etude_hydraulique.tex
pdflatex Etude_sonde_conductivite.tex
pdflatex Schema_sonde_conductivite.tex
```

`Etude_sonde_conductivite.tex` a besoin de `logo_upf.png`, présent dans son dossier.
Les PDF déjà compilés des études sont dans `documents/`.
