# Nexa memory design

Nexa keeps memory in two tiers.

## Short-term memory

Short-term memory is the recent conversation. Every message is written to the
SQLite `messages` table with a role and a timestamp. Before each reply Nexa
loads the last twelve messages verbatim and passes them to the model as chat
history. This tier is exact, needs no embeddings, and is scoped to a single
conversation. When the conversation ends, its short-term context is gone.

## Long-term memory

Long-term memory holds durable facts about the user: preferences, goals,
standing instructions, relationships, and stable facts. After each turn a small
extraction prompt asks the model to pull out anything worth keeping and return
it as JSON. Each fact is stored as a row in the `memories` table and as a vector
in ChromaDB. A new fact is skipped if it is almost identical to one already
stored.

## Recall and ranking

When a new message arrives, Nexa embeds it and searches the memory vectors.
Candidates are then ranked by a weighted score rather than raw similarity:

    score = 0.60 * similarity
          + 0.20 * (importance / 10)
          + 0.12 * recency
          + 0.08 * frequency

Recency decays with the age of the memory; frequency counts how often the
memory has been recalled before. The top five memories are added to the prompt.

## People and relationships

Relationships are modelled as a person, a relation, and the target of that
relation, for example "Anchal is the sister of the user". Extra facts can be
attached to a person over time.
