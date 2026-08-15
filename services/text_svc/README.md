# text_svc

Stateless text normaliser: NFKC unicode normalisation, whitespace collapsing, quoted-reply
stripping, a lightweight script-based language hint, and a regex PII scan (email/phone/card/NIC)
that raises `PII_DETECTED`. Consumes `tickets.text.work`, publishes `tickets.text.done`. Owns no
table, the normalised text and flags travel in the event body.
