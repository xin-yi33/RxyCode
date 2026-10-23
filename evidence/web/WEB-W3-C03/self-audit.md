# WEB-W3-C03 self-audit

- RED: the reducer and chat page were missing. See red.txt.
- reduceEvents is the shipped function. Events 1,2,2,4 stay at 1,2 until seq 3 arrives, then the order is 1,2,3,4 and seq 2 is kept once.
- Intermediate deltas stay in intermediate. assistant.final replaces the answer with its own text. The answer does not end with the child thought.
- ChatPage loads GET /events?after_seq=0&follow=0, then opens EventSource with follow=1 so a dropped connection sends Last-Event-ID. A 409 CURSOR_EXPIRED renders 重新同步 and removes the answer node.
- The integration seeds tool.failed, an intermediate delta, assistant.final, and approval.requested through the real server. After reload the tool card still says 失败, the approval still says 等待审批, and the answer is still the final text. Pruning seq 1 makes the next open show 重新同步.
- A failed tool is not rendered as 成功. Approval status stays pending until approval.resolved.
- Not claimed as 已落实. WEB-W1 CW03 and CW04 stay open. Device connect is not implemented.
