# PFE_UPDATE — Récapitulatif des mises à jour du projet

Projet : **CRED-HUUNT v2** — système agentique de détection et de tri de
secrets / identifiants (« credentials ») à l'aide de petits modèles de langage
(SLM) et d'IA agentique.

Ce document explique simplement **tout ce qui a été mis à jour** dans le projet.

---

## Vue d'ensemble

Le projet est organisé en trois couches :

1. **Classifieur d'exécution** (`src/`) — décide si une valeur détectée est un
   vrai secret.
2. **Couche données** (`scripts/`) — construit et augmente le jeu de données.
3. **Couche benchmark** (`scripts/`) — compare les modèles et les stratégies de
   raisonnement.

Les mises à jour touchent les trois couches, plus la documentation et le
notebook d'entraînement.

---

## 1. Choix des modèles SLM

**Avant :** trois modèles dont deux de la même famille (`qwen2.5:1.5b` et
`qwen2.5-coder:3b`) — on ne pouvait pas comparer les architectures.

**Après :** un trio **diversifié** (3 familles différentes, ~2-3 milliards de
paramètres) :

| Modèle | Famille | Pourquoi |
|---|---|---|
| `qwen2.5-coder:3b` | Alibaba (spécialisé code) | meilleur petit modèle pour le code/config |
| `granite3.3:2b` | IBM (agentique) | discipliné pour produire du JSON |
| `llama3.2:3b` | Meta (généraliste) | famille différente, sert de référence |

Cela permet de répondre à la question : *quelle famille de petit modèle est la
meilleure pour le tri de secrets ?*

---

## 2. Stratégies de raisonnement (5 stratégies)

Cinq stratégies sont maintenant testées, et **deux qui étaient cassées ont été
corrigées** :

| Stratégie | Rôle | Mise à jour |
|---|---|---|
| `direct_json` | réponse directe (référence) | — |
| `few_shot` | exemples dans le prompt | — |
| `self_consistency` | plusieurs votes sur les cas limites | **corrigée** : ne lance les votes multiples que si le modèle hésite (confiance 0,4–0,6), pas à chaque fois — économise du temps de calcul |
| `cot_distilled` | raisonnement appris d'un modèle « professeur » | **ajoutée** : nouveau script `distill_rationales.py` qui génère les explications |
| `react_triage` | boucle agentique ReAct | **corrigée** : vraie boucle itérative (le modèle pense → utilise un outil → observe → recommence) au lieu d'un simple appel unique |

Les outils de la boucle ReAct sont regroupés dans un registre (`TOOL_REGISTRY`)
— ajouter un outil ne demande qu'une seule ligne.

---

## 3. Métriques d'évaluation

De nouvelles mesures ont été ajoutées aux benchmarks :

- **`schema_validity_rate`** — le JSON produit respecte-t-il le contrat v2 ?
- **`evidence_grounding_score`** — les preuves citées sont-elles réelles ?
- **`p95` / `p99` de latence** — temps de réponse dans les pires cas.
- **`escalation_rate`** — fréquence des cas limites (pour `self_consistency`).

---

## 4. Générateur de données synthétiques AXA *(nouveauté principale)*

Nouveau script : **`scripts/generate_axa_synthetic.py`**.

Il crée un jeu de données synthétique réaliste, adapté au contexte de
l'entreprise **AXA Group**, pour entraîner les modèles.

**Comment il fonctionne :** il *extrait* le vocabulaire AXA des fichiers
sources réels (domaines `.intraxa`, préfixes, tickets) puis *recombine* ces
éléments de façon compositionnelle :

- **10 langues** : anglais, français, allemand, espagnol, italien, portugais,
  néerlandais, polonais, turc, japonais.
- **~55 types de credentials** : mots de passe, clés cloud (AWS, Azure, GCP),
  jetons SaaS (GitHub, GitLab, Stripe, Slack, Twilio…), clés IA (OpenAI,
  Anthropic, Hugging Face), JWT, clés privées (RSA, EC, PGP, SSH…), secrets
  SAML/ADFS, keytabs Kerberos, mots de passe SAP et mainframe, etc.
- **~16 supports (« carriers »)** : fichiers `.properties` / `.yml` / `.json`,
  code Java / Python / C# / JS / Go, commandes, en-têtes HTTP, chaînes de
  connexion, blocs PEM, messages de chat, tickets…
- **Noms de clés variés** : `password`, `pwd`, `DB_PASSWORD`, `motDePasse`,
  `mot_de_passe`, `contrasena`, `passwort`… dans toutes les casses.

**Trois fichiers produits :**

| Fichier | Étiquette | Contenu |
|---|---|---|
| `true_positive.crdownload` | `REAL` | vrais secrets |
| `false_positive.crdownload` | `FALSE_POSITIVE` | bruit qui ressemble à un secret |
| `review.crdownload` | `REVIEW` | cas ambigus — le modèle doit hésiter |

Volume par défaut : **4000 + 4000 + 700 = 8700 enregistrements**.

Documentation associée : **`docs_v2/AXA_SYNTHETIC_DATASET.md`**.

---

## 5. Pipeline de traitement des données

Le script `scripts/process_synthetic_training_data.py` a été mis à jour :

- Nouveaux paramètres **`--source-tp` / `--source-fp` / `--source-review`**
  pour utiliser les fichiers du générateur AXA au lieu des fichiers par défaut.
- Prise en charge de la **classe `REVIEW`** (cas ambigus).

Résultat après traitement (augmentation des faux positifs ×3) :
`REAL 4000 / FALSE_POSITIVE 16000 / REVIEW 700` → découpage **train 16 563 /
validation 2 052 / test 2 085** (découpage sans fuite de contexte entre les
ensembles).

---

## 6. Fine-tuning (LoRA / QLoRA)

Le script `scripts/lora_fine_tune.py` accepte maintenant l'option
**`--load-4bit`** : il charge le modèle de base en **4 bits (QLoRA)**, ce qui
permet d'entraîner un modèle de 3 milliards de paramètres sur un GPU de petite
taille (≤ 8 Go de mémoire).

- **LoRA** : modèle de base en 16 bits — utilisé sur Kaggle (GPU 16 Go).
- **QLoRA** : modèle de base en 4 bits — utilisé sur les petits GPU.

---

## 7. Notebook Kaggle

Le notebook `notebooks/kaggle_train_eval_pipeline.ipynb` a été enrichi pour
être un véritable tableau de bord :

- **Choix des modèles** — liste `MODELS` : on active les modèles à entraîner.
- **Choix des stratégies** — liste `STRATEGIES` : on choisit les stratégies à
  tester.
- **Choix du jeu de données** — `USE_AXA_GENERATOR` : utilise le générateur AXA.
- **Interrupteurs d'étapes** — `RUN_TRAINING`, `RUN_EVALUATION`,
  `RUN_STRATEGY_BENCHMARK`.
- **Nouvelle section 7 — Benchmark des stratégies** : compare les modèles ×
  stratégies et produit un résumé des résultats.

Le notebook fait désormais tout l'enchaînement : générer les données AXA →
traiter → entraîner → évaluer → comparer les stratégies → archiver les résultats.

---

## 8. Documentation

Plusieurs documents ont été créés pour donner au projet une qualité
« entreprise » :

- **Documents d'entreprise** : `SECURITY.md`, `MODEL_CARD.md`,
  `THREAT_MODEL.md`, `DATA_GOVERNANCE.md`, `PRODUCTION_DEPLOYMENT.md`,
  `CONTRIBUTING.md`, `CHANGELOG.md`, `ROADMAP.md`.
- **Décisions d'architecture (ADR)** : `docs_v2/adr/` — 4 décisions documentées
  (choix du trio de modèles, self-consistency conditionnelle, boucle ReAct,
  report de Tree-of-Thoughts / Graph-of-Thoughts).
- **`docs_v2/AXA_SYNTHETIC_DATASET.md`** : guide du générateur AXA.
- Mises à jour de `CLAUDE.md`, `docs_v2/README.md`, `docs_v2/RUNBOOK.md`.

---

## Récapitulatif des fichiers

**Nouveaux fichiers :**

| Fichier | Rôle |
|---|---|
| `scripts/generate_axa_synthetic.py` | générateur de données synthétiques AXA |
| `scripts/distill_rationales.py` | génération des explications « professeur » |
| `docs_v2/AXA_SYNTHETIC_DATASET.md` | documentation du générateur |
| `docs_v2/adr/*` | décisions d'architecture |
| `SECURITY.md`, `MODEL_CARD.md`, `THREAT_MODEL.md`, … | documents d'entreprise |

**Fichiers modifiés :**

| Fichier | Modification |
|---|---|
| `src/llm_client.py` | modèle par défaut mis à jour |
| `src/prompt_builder.py` | ajout du prompt système ReAct |
| `scripts/reasoning_runner.py` | self-consistency conditionnelle, boucle ReAct |
| `scripts/react_tools.py` | registre d'outils `TOOL_REGISTRY` |
| `scripts/benchmark_models.py` | nouveau trio + nouvelles métriques |
| `scripts/evaluate_model_performance.py` | nouvelles métriques |
| `scripts/process_synthetic_training_data.py` | paramètres `--source-*`, classe `REVIEW` |
| `scripts/lora_fine_tune.py` | option QLoRA `--load-4bit` |
| `scripts/test_trained_model.py` | nouveau trio de modèles |
| `notebooks/kaggle_train_eval_pipeline.ipynb` | choix des modèles / stratégies, benchmark |
| `CLAUDE.md`, `docs_v2/README.md`, `docs_v2/RUNBOOK.md` | documentation |

---

## Conclusion

Le projet est passé d'un simple classifieur à un **système agentique complet** :
un trio de modèles diversifié, cinq stratégies de raisonnement fonctionnelles,
des métriques d'évaluation complètes, un **générateur de données synthétiques
AXA multilingue couvrant ~55 types de credentials**, un pipeline d'entraînement
LoRA / QLoRA, et un notebook Kaggle prêt à l'emploi.
