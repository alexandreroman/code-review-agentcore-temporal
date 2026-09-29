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

# Completion times of the UpdateCheck activities, oldest first. A review round
# completes two of them: in_progress, then the conclusion.
def check_updates: [activities[] | select(.name == "UpdateCheck" and .completed) | .completed] | sort;

# E2E-02 bookkeeping for one history, around the /kill time $kill.
def kill_report($kill):
  activities
  | {finished_before: [.[] | select(.completed and .completed < $kill)] | length,
     retried_before: [.[] | select(.completed and .completed < $kill and .attempt > 1)] | length,
     interrupted: [.[] | select(.attempt > 1 and .scheduled < $kill)] | length};

# Worker identities that started an activity attempt before $kill: the killed
# sessions, even when the task queue listed no poller at the time.
def identities_before($kill):
  [activities[] | select(.started and .started < $kill) | .identity // empty] | unique;

# Start times of the activity attempts (any attempt number) started after $kill
# by an AgentCore session absent from $killed: the work resumed elsewhere.
def starts_elsewhere($kill; $killed):
  [activities[]
   | select(.started and .started > $kill and ((.identity // "") | startswith("agentcore:"))
            and (.identity as $i | $killed | index($i) | not))
   | .started];

# Decode a json/plain payload ({metadata, data}) into the value it carries;
# any other object passes through unchanged. `temporal ... -o json` leaves
# payloads base64-encoded, it does not decode them.
def decoded:
  if (.metadata.encoding? // "") == "anNvbi9wbGFpbg==" and (.data | type) == "string"
  then (.data | @base64d | fromjson)
  else . end;

# Value returned by a completed execution: the first object of the completion
# event that has every key of $keys, decoding json/plain payloads first.
def result_with($keys):
  [.events[] | select(.workflowExecutionCompletedEventAttributes) | .. | objects
   | decoded | .. | objects
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

# E2E-04: marks each defect of expected-findings (as JSON) found in $findings (rules: its header).
def coverage($findings):
  .defects | map(. as $d | {id, category: $d.category,
    found: any($findings[]; . as $f
      | $f.category == $d.category and $f.path == $d.file
      and any($d.line_ranges[]; $f.line <= .[1] and ($f.end_line // $f.line) >= .[0]))});
