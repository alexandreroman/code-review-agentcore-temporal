# jq helpers of the e2e-validation skill, for the JSON printed by the
# Temporal CLI (`temporal ... -o json`) and for expected-findings.yaml once
# converted to JSON. Load with:
#   jq -L .claude/skills/e2e-validation 'include "e2e"; ...'
#
# The CLI prints protobuf JSON: 64-bit integers may be strings, and empty or
# zero fields are left out, hence the `tostring` and the `// default` below.

# RFC 3339 time, with an optional fraction (nanoseconds included) -> epoch seconds.
def ts:
  (sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601)
  + ((capture("\\.(?<f>[0-9]+)Z$").f // "0") | "0.\(.)" | tonumber);

# Start of the execution whose history is the input.
def started_at: .events[0].eventTime | ts;

# Workflow tasks of a history: [{t, identity}].
def workflow_tasks:
  [.events[] | select(.workflowTaskStartedEventAttributes)
   | {t: (.eventTime | ts), identity: .workflowTaskStartedEventAttributes.identity}];

# Activities of a history, one object per scheduled activity:
# {name, scheduled, attempt, started, identity, completed}; the last four
# appear once the activity has finished (a retried activity records its
# started event, with the final attempt number, when it completes).
def activities:
  reduce .events[] as $e ({};
    if $e.activityTaskScheduledEventAttributes then
      .[$e.eventId | tostring] = {
        name: $e.activityTaskScheduledEventAttributes.activityType.name,
        scheduled: ($e.eventTime | ts)}
    elif $e.activityTaskStartedEventAttributes then
      .[$e.activityTaskStartedEventAttributes.scheduledEventId | tostring] += {
        attempt: ($e.activityTaskStartedEventAttributes.attempt // 1),
        started: ($e.eventTime | ts),
        identity: $e.activityTaskStartedEventAttributes.identity}
    elif $e.activityTaskCompletedEventAttributes then
      .[$e.activityTaskCompletedEventAttributes.scheduledEventId | tostring] += {completed: ($e.eventTime | ts)}
    else . end)
  | [.[]];

# Completion times of the set_check activities, oldest first. A review round
# completes two of them: in_progress, then the conclusion.
def check_updates: [activities[] | select(.name == "set_check" and .completed) | .completed] | sort;

# E2E-03 bookkeeping for one history, around the /kill time $kill.
def kill_report($kill):
  activities
  | {finished_before: [.[] | select(.completed and .completed < $kill)] | length,
     retried_before: [.[] | select(.completed and .completed < $kill and .attempt > 1)] | length,
     interrupted: [.[] | select(.attempt > 1 and .scheduled < $kill)] | length};

# Start times of the retried attempts run by an AgentCore session absent from $killed.
def resumed_starts($killed):
  [activities[]
   | select(.attempt > 1 and ((.identity // "") | startswith("agentcore:"))
            and (.identity as $i | $killed | index($i) | not))
   | .started];

# Value returned by a completed execution: the first object of the completion
# event that has every key of $keys (the CLI decodes json/plain payloads).
def result_with($keys):
  [.events[] | select(.workflowExecutionCompletedEventAttributes) | .. | objects
   | select(. as $o | all($keys[]; . as $k | $o | has($k)))]
  | first;

# AgentCore identities in `temporal task-queue describe -o json`. The list
# keeps the sessions seen in the last ~5 minutes, dead ones included.
def agentcore_identities:
  [.. | objects | .identity? // empty | strings | select(startswith("agentcore:"))] | unique;

# Latest poll of an AgentCore worker (epoch seconds), or null.
def agentcore_last_poll:
  [.. | objects | select(((.identity? // "") | tostring | startswith("agentcore:")) and .lastAccessTime?)
   | .lastAccessTime | ts]
  | max;

# E2E-04. Input: expected-findings as JSON. For each defect, found is true
# when a finding of $findings has the defect's category, its file as path,
# and a span [line, end_line or line] overlapping one of its line_ranges
# (bounds included).
def coverage($findings):
  .defects | map(. as $d | {id, category: $d.category,
    found: any($findings[]; . as $f
      | $f.category == $d.category and $f.path == $d.file
      and any($d.line_ranges[]; $f.line <= .[1] and ($f.end_line // $f.line) >= .[0]))});
