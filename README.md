# lead-triage-agent

**Qualify, score, route and escalate inbound leads — with an explanation for every decision and a human in the loop where it matters.**

[![CI](https://github.com/walidsadfi-evolurise/lead-triage-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/walidsadfi-evolurise/lead-triage-agent/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)

*[Version française plus bas](#version-française)*

A contact form, a shared mailbox and a chat widget all dump the same thing on a team: free text from someone who may be a hot prospect, a job seeker, a spammer, or a patient bleeding after an extraction. This agent reads each lead, decides **who gets it, how fast, and whether a machine is allowed to answer first**, and writes down why.

It is the generalised version of what I deployed for a multi-site medical group: leads from several sites and channels, routed to the right front desk within minutes, with urgent and sensitive cases always landing on a human.

```text
$ triage run examples/leads.json

Claire Martin → auto_reply · team lyon-front-desk · SLA 4h · score 67 (B)
   appointment request (16 words)
    +35  intent: intent = appointment
    +15  urgency: urgency = high
    +10  contact: phone number provided
     +7  timeline: timeline mentioned (cette semaine)
   • rule 'appointment-lyon' → team lyon-front-desk
   draft: Bonjour Claire, Merci pour votre message. Un membre de l'équipe vous rappelle sous 4 h…

Marc → escalate · team on-call · SLA 1h · score 27 (D) · needs human
   • rule 'emergency-any' → team on-call
   • sensitive content: no automatic reply
   • emergency: escalated to a human now

promo@mail.ru → discard · team none · score 0 (D)
   • classified as spam
```

## How a decision is made

```
lead ──► extract ──► score ──► route ──► guardrails ──► decision + audit line
         (LLM or     (named     (YAML      (override
          rules)      factors)   rules)     anything)
```

1. **Extract** — intent, service, urgency, location, timeline, language, *sensitive?*, confidence. An LLM returns strict JSON validated by pydantic; on any failure (bad JSON, provider down, no key) a **rule-based extractor** takes over with capped confidence. Tests run on the rules, no network.
2. **Score** — every point has a name and a one-line reason (`+10 contact: phone number provided`). Weights live in `routing.yaml`, so sales ops can tune them. Tiers A/B/C/D.
3. **Route** — declarative rules, first match wins: by intent, urgency, tier, service, location, language, channel, score range. The model reads; it does not pick the team.
4. **Guardrails** — applied after routing and able to override it:
   - emergency → `escalate`, human now, 1 h SLA
   - sensitive content (health, legal, money trouble, minors) → never an automatic reply
   - low extraction confidence → human review
   - tier below the auto-reply threshold → assign instead
   - spam → discard
5. **Audit** — one JSONL line per decision with the factors and reasons, email masked, no phone, no message body. Also used for deduplication.
6. **Evaluate** — `triage eval cases.yaml` replays labelled leads: team / action / tier / intent accuracy and **escalation recall**. `--min-pass-rate` makes it a CI gate.

## Quick start

```bash
pip install -e ".[dev]"
triage run examples/leads.json          # rules extractor, no keys needed
triage eval evalsets/demo.yaml          # 9 labelled cases, 100 %
triage serve                            # POST /leads webhook
```

With a model:

```bash
export TRIAGE_LLM_PROVIDER=anthropic TRIAGE_LLM_MODEL=claude-haiku-4-5 TRIAGE_ANTHROPIC_API_KEY=…
# or any OpenAI-compatible endpoint (OpenAI, Mistral, Groq, vLLM, Ollama /v1):
export TRIAGE_LLM_PROVIDER=openai TRIAGE_LLM_MODEL=gpt-4o-mini TRIAGE_OPENAI_API_KEY=…
```

### Webhook

```bash
curl -s -X POST localhost:8000/leads -H "Authorization: Bearer $TRIAGE_API_TOKEN" \
  -H 'content-type: application/json' \
  -d '{"name":"Claire","email":"c@example.org","phone":"+33612345678","message":"Rendez-vous à Lyon cette semaine svp","source":"/lyon/"}'
```

Returns the full `Decision` (extraction, score with factors, route, action, `needs_human`, reasons, reply draft). `?dry_run=true` skips the audit log; duplicates (same contact + same message) get a `409`.

Wire it from the contact form (a WordPress hook, Gravity Forms webhook, HubSpot workflow…), then act on the decision: create the CRM task for `route.team`, send `reply_draft` when `action == "auto_reply"`, page someone when `action == "escalate"`.

## Configuration

| Variable | Default | |
|---|---|---|
| `TRIAGE_ROUTING_FILE` | `routing.yaml` | rules, weights, templates |
| `TRIAGE_AUDIT_FILE` | `data/audit.jsonl` | append-only decision log |
| `TRIAGE_LLM_PROVIDER` | `rules` | `rules` · `anthropic` · `openai` |
| `TRIAGE_LLM_MODEL` | `claude-haiku-4-5` | |
| `TRIAGE_API_TOKEN` | – | bearer token for the webhook |
| `TRIAGE_DEDUPE` | `true` | reject already-seen leads |

`routing.yaml` in this repo is a working example for a multi-site clinic group (Lyon, Paris, English speakers, on-call, HR, support). Replace teams, services and locations with yours; keep the emergency rule first.

## Design notes

- **The LLM extracts, rules decide.** Routing stays auditable, editable without a deploy, and identical across model versions. Swapping the model changes extraction quality — which the eval set measures — not who receives what.
- **Confidence is a first-class output.** Low confidence doesn't fail; it adds a human. The rule-based fallback caps its own confidence so the system knows when it is flying blind.
- **Guardrails run last** and can only make the outcome more careful (auto-reply → assign → escalate), never less.
- **The audit log is for the question you'll get in six months**, not for analytics; it keeps reasons, not personal data.

## Project layout

```
src/triage/
  models.py     Lead, Extraction, Score, Route, Decision (pydantic)
  extract.py    SYSTEM_PROMPT, LLMExtractor (JSON + fallback), RuleBasedExtractor
  scoring.py    ScoringWeights, score_lead → named factors
  routing.py    RoutingConfig / Rule / Match, first-match routing
  agent.py      TriageAgent.decide — pipeline + guardrails + reply draft
  audit.py      JSONL audit with PII minimisation and dedupe
  evaluate.py   labelled cases → accuracy and escalation recall
  api.py        FastAPI webhook      cli.py  triage run | eval | serve
routing.yaml    example config       evalsets/demo.yaml   examples/leads.json
```

## Roadmap

- [ ] Connectors: HubSpot / Pipedrive task creation, Slack escalation
- [ ] Reply drafting by the model, constrained by templates and the sensitive flag
- [ ] Multi-label intents (appointment **and** quote)
- [ ] Nightly eval on anonymised production leads

## License

MIT — see [LICENSE](LICENSE). Built by [Walid Sadfi](https://www.malt.fr/profile/walidsadfi), Forward Deployed Engineer · agents IA & WooCommerce.

---

## Version française

**Qualifier, scorer, router et escalader les leads entrants, avec une explication pour chaque décision et un humain dans la boucle là où ça compte.**

Formulaire de contact, boîte mail partagée, widget de chat : tout arrive au même endroit, en texte libre, et ça peut être un prospect chaud, un candidat, un spammeur ou un patient qui saigne après une extraction. Cet agent lit chaque lead, décide **qui le reçoit, sous quel délai, et si une machine a le droit de répondre en premier**, et note pourquoi.

C'est la version généralisée de ce que j'ai déployé pour un groupe médical multi-sites : des leads de plusieurs sites et canaux, routés vers le bon accueil en quelques minutes, les cas urgents et sensibles atterrissant toujours chez un humain.

- **Extraction** par LLM (JSON strict validé) avec repli sur des règles quand le modèle échoue ; les tests tournent sans réseau.
- **Score explicable** : chaque point a un nom et une raison, les poids sont dans `routing.yaml`.
- **Routage déclaratif** : le modèle lit, les règles décident. Modifiable sans redéploiement.
- **Garde-fous** : urgence → escalade immédiate ; contenu sensible → jamais de réponse automatique ; faible confiance → relecture humaine ; spam → rejet.
- **Journal d'audit** sans données personnelles, dédoublonnage, webhook FastAPI, CLI, jeu d'évaluation avec rappel d'escalade comme barrière CI.

```bash
pip install -e ".[dev]"
triage run examples/leads.json
triage eval evalsets/demo.yaml
```

Vous recevez des leads de plusieurs sources et l'équipe perd du temps à trier ? [Parlons-en sur Malt](https://www.malt.fr/profile/walidsadfi) : en 30 jours, un agent en production sur vos vrais leads, avec un point de mesure.
