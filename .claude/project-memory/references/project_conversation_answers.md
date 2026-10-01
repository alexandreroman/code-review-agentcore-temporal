---
name: "Conversation answers policy"
description: "How the bot answers plain Conversation comments: mention rule, code-only scope, collaborator context"
type: project
---

# Conversation answers policy

The bot answers plain comments in a pull request's Conversation tab, in
addition to replies in finding threads. Review threads opened by humans
stay out of scope.

- A mention of the bot always gets a post (an answer or a fixed text) and
  an 👀 reaction. Without a mention, the agent answers only a comment
  addressed to it, and stays silent otherwise.
- The agent discusses only this repository's code and this pull request:
  topics it can check by reading the code. Any other topic gets a fixed,
  code-written text when the bot is mentioned, and silence otherwise.
- The agent reads Conversation comments from the bot and from OWNER,
  MEMBER or COLLABORATOR authors (`author_association`); strangers stay
  out of its context.
- The Conversation agent has no verdict: dismissals happen only in a
  finding's thread. A per-PR answer budget caps the cost.

**Why:** the bot must not answer anything and everything, nor chime in on
discussions between humans; every answered comment costs Bedrock tokens.

**How to apply:** keep the scope rule and the fixed off-topic text when
changing the Conversation prompt or adding triggers; review any widening
of the context or of the trigger with the user first.
