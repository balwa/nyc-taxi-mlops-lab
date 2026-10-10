#!/usr/bin/env bash
# Does Claude Code load this repo's rules? It should read the root AGENTS.md wherever you start it,
# plus the AGENTS.md of the directory you're in (infra/, pipelines/). This asks it, from the repo root,
# infra/ and pipelines/, with every tool disabled, for the check word at the end of each AGENTS.md.
#
#   make agent-check        (or scripts/agent-check.sh)
#
# Three short requests on your Claude plan. Exit 0 when every directory shows every expected word.
set -uo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
command -v claude >/dev/null || { echo "claude (Claude Code) isn't on your PATH" >&2; exit 2; }
prompt='Reply with every "check word" given in your instructions or project context, one per line, and nothing else. Do not use any tools. If you were given none, reply NONE.'
bad=0

check() { # DIR WORD...
  local dir=$1 out word
  shift
  out=$(cd "$root/$dir" && claude -p "$prompt" --disallowedTools "Bash,Read,Grep,Glob,Edit,Write,WebFetch,WebSearch,Task" </dev/null 2>/dev/null) || true
  for word in "$@"; do
    if grep -q -- "$word" <<<"$out"; then
      printf 'OK    %-10s %s\n' "$dir" "$word"
    else
      printf 'FAIL  %-10s %s missing (answer: %s)\n' "$dir" "$word" "$(tr '\n' ' ' <<<"$out" | cut -c1-120)"
      bad=1
    fi
  done
}

check . lab-rules-root
check infra lab-rules-root lab-rules-infra
check pipelines lab-rules-root lab-rules-pipelines
(( bad )) && echo "Your agent isn't loading every AGENTS.md. Update Claude Code (claude update) and start it from inside this repo." >&2
exit $bad
