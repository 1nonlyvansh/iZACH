"""
CalendarAgent — full LLM-driven handler for all calendar, reminder, and alarm commands.

Replaces/consolidates in command_chain.py:
  _handle_calendar_voice_command()     — cancel/reschedule/add/view calendar
  "remind me" block (line ~2653)       — scheduler.add_reminder()
  "set alarm" block (line ~1941)       — system_control.set_alarm()
  _CALENDAR_TRIGGERS keyword block     — routed here from fast-path

Intents handled:
  view_schedule      today/upcoming events
  next_event         single next upcoming event
  add_event          add to Google Calendar
  cancel_event       cancel/delete a calendar event
  reschedule_event   move event to new time/date
  add_reminder       schedule an in-memory reminder (speaks when due)
  list_reminders     list pending reminders
  set_alarm          set OS alarm via system_control
  clear_calendar     delete ALL upcoming events
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")

# ── Intent parser prompt ─────────────────────────────────────────
_PARSE_PROMPT = """\
You are iZACH's calendar/reminder/alarm command parser. Parse this voice command into JSON.

Today is: {today_name} ({today})
Command: "{cmd}"

Output ONLY valid JSON — no other text:
{{
  "intent": "<intent>",
  "event_title": "<event name or null>",
  "date": "<YYYY-MM-DD or null>",
  "time": "<HH:MM 24h or null>",
  "original_time": "<HH:MM 24h or null — OLD time for reschedule>",
  "new_time": "<HH:MM 24h or null — NEW time for reschedule>",
  "new_date": "<YYYY-MM-DD or null — for reschedule>",
  "link": "<URL or null>",
  "reminder_task": "<what to remind about, or null>",
  "reminder_time": "<natural language time string for reminder, or null>",
  "alarm_hour": <int 0-23 or null>,
  "alarm_minute": <int 0-59 or null>,
  "window_hours": <int — how many hours ahead to show, default 72>
}}

Intents (pick exactly one):
- view_schedule     : "what's on my calendar", "my schedule", "upcoming events", "show events"
- next_event        : "what's my next event", "next appointment", "what do I have next"
- add_event         : "add X to calendar", "schedule X at Y", "put X on calendar"
- cancel_event      : "cancel my X", "X is cancelled", "remove X from calendar"
- reschedule_event  : "move X to Y", "X now at Y instead of Z", "reschedule X"
- add_reminder      : "remind me to X at Y", "set a reminder for X at Y"
- list_reminders    : "list reminders", "what reminders", "my reminders"
- set_alarm         : "set alarm", "wake me up at", "alarm for", "alarm at"
- clear_calendar    : "clear my calendar", "delete all events", "remove all events"

Rules:
- "tomorrow" = one day after {today}; compute the actual YYYY-MM-DD
- "7pm" = 19:00, "7am" = 07:00, "7:30pm" = 19:30
- "7 baje" = 07:00 (morning context) or 19:00 (evening — use surrounding words)
- reschedule: original_time = OLD time, new_time = NEW time
- For add_event: date defaults to today if not specified; time defaults to null (ask)
- reminder_time: keep as the user's natural language phrase (e.g. "5pm", "in 2 hours", "every morning")
- alarm_hour/alarm_minute: extract from "7am", "7:30", "7:30 am" etc.
- window_hours: default 72 (3 days) for view_schedule
- Output ONLY the JSON object
"""


class CalendarAgent:
    """
    Handles all calendar/reminder/alarm domain commands via LLM intent parsing.
    """

    def __init__(self, speak_fn, raw_ai_fn, scheduler):
        self.speak      = speak_fn
        self._raw_ai    = raw_ai_fn
        self.scheduler  = scheduler   # modules.scheduler.TaskScheduler instance

    # ── Public entry point ────────────────────────────────────────

    def handle(self, cmd: str, domain_ctx: dict) -> bool:
        """
        Parse and execute calendar/reminder/alarm command.
        Returns True if handled, False to fall through to command_chain.
        """
        intent_data = self._parse_intent(cmd)
        intent      = intent_data.get("intent", "unknown")
        print(f"[CAL_AGENT] intent={intent} data={intent_data}")

        dispatch = {
            "view_schedule":    self._view_schedule,
            "next_event":       self._next_event,
            "add_event":        self._add_event,
            "cancel_event":     self._cancel_event,
            "reschedule_event": self._reschedule_event,
            "add_reminder":     self._add_reminder,
            "list_reminders":   self._list_reminders,
            "set_alarm":        self._set_alarm,
            "clear_calendar":   self._clear_calendar,
        }

        handler = dispatch.get(intent)
        if handler:
            return handler(intent_data, cmd)
        return False

    # ── Intent parser ─────────────────────────────────────────────

    def _parse_intent(self, cmd: str) -> dict:
        now        = datetime.now(tz=_IST)
        today      = now.strftime("%Y-%m-%d")
        today_name = now.strftime("%A, %d %B %Y")
        prompt     = _PARSE_PROMPT.format(cmd=cmd, today=today, today_name=today_name)
        response   = ""
        try:
            response = self._raw_ai(prompt)
            # Strip markdown fences if model adds them
            clean = re.sub(r'^```(?:json)?\s*', '', response.strip(), flags=re.IGNORECASE)
            clean = re.sub(r'\s*```$', '', clean)
            m = re.search(r'\{.*\}', clean, re.DOTALL)
            if not m:
                return {"intent": "unknown"}
            data = json.loads(m.group())
            if "intent" not in data:
                return {"intent": "unknown"}
            return data
        except Exception as e:
            print(f"[CAL_AGENT] parse error: {e} | response: {response!r}")
            return {"intent": "unknown"}

    # ── Helpers ───────────────────────────────────────────────────

    def _fmt_time(self, hhmm: str) -> str:
        """'19:00' → '7:00 PM'"""
        try:
            return datetime.strptime(hhmm, "%H:%M").strftime("%I:%M %p").lstrip("0")
        except Exception:
            return hhmm

    def _fmt_date(self, yyyymmdd: str) -> str:
        """'2026-05-22' → '22 May'"""
        try:
            return datetime.strptime(yyyymmdd, "%Y-%m-%d").strftime("%d %B")
        except Exception:
            return yyyymmdd

    def _today(self) -> str:
        return datetime.now(tz=_IST).strftime("%Y-%m-%d")

    # ── Handlers ─────────────────────────────────────────────────

    def _view_schedule(self, d: dict, cmd: str) -> bool:
        hours = int(d.get("window_hours") or 72)
        try:
            from modules.calendar_agent import get_upcoming_events, format_event_for_speech
            events = get_upcoming_events(hours=hours)
            if not events:
                self.speak(f"Nothing on your calendar for the next {hours // 24} days.")
                return True
            parts = [format_event_for_speech(e) for e in events[:5]]
            self.speak("Coming up: " + ", then ".join(parts) + ".")
        except Exception as e:
            self.speak(f"Couldn't read calendar: {e}")
        return True

    def _next_event(self, d: dict, cmd: str) -> bool:
        try:
            from modules.calendar_agent import get_next_event, format_event_for_speech
            event = get_next_event()
            if not event:
                self.speak("Nothing coming up on your calendar.")
            else:
                self.speak("Next up: " + format_event_for_speech(event) + ".")
        except Exception as e:
            self.speak(f"Couldn't read calendar: {e}")
        return True

    def _add_event(self, d: dict, cmd: str) -> bool:
        title = (d.get("event_title") or "").strip()
        date  = d.get("date") or self._today()
        time  = d.get("time") or d.get("new_time")
        link  = d.get("link")

        if not title:
            self.speak("What should I call this event?")
            return True
        if not time:
            self.speak(f"At what time should I add {title}?")
            return True

        try:
            from modules.calendar_agent import add_event
            event = add_event(title=title, date_str=date, time_str=time, link=link)
            if event:
                self.speak(
                    f"Added {title} at {self._fmt_time(time)} on {self._fmt_date(date)} to your calendar."
                )
            else:
                self.speak("Couldn't add the event. Calendar error.")
        except Exception as e:
            self.speak(f"Calendar error: {e}")
        return True

    def _cancel_event(self, d: dict, cmd: str) -> bool:
        title_hint = (d.get("event_title") or "").strip()
        orig_date  = d.get("date")

        if not title_hint:
            self.speak("Which event should I cancel?")
            return True

        try:
            from modules.calendar_agent import find_event_by_voice_cmd, cancel_event
            mapping = find_event_by_voice_cmd(title_hint, orig_date)
            if not mapping:
                self.speak(f"I couldn't find a {title_hint} event on your calendar.")
                return True
            ok = cancel_event(mapping["calendar_event_id"])
            if ok:
                self.speak(
                    f"{mapping.get('title', title_hint)} cancelled and removed from your calendar."
                )
            else:
                self.speak("Couldn't remove the event. Calendar error.")
        except Exception as e:
            self.speak(f"Calendar error: {e}")
        return True

    def _reschedule_event(self, d: dict, cmd: str) -> bool:
        title_hint  = (d.get("event_title") or "").strip()
        orig_date   = d.get("date")
        new_time    = d.get("new_time")
        new_date    = d.get("new_date")

        if not title_hint:
            self.speak("Which event should I reschedule?")
            return True
        if not new_time and not new_date:
            self.speak("When should I move it to?")
            return True

        try:
            from modules.calendar_agent import find_event_by_voice_cmd, update_event
            mapping = find_event_by_voice_cmd(title_hint, orig_date)
            if not mapping:
                self.speak(f"I couldn't find a {title_hint} event to reschedule.")
                return True
            ok = update_event(
                mapping["calendar_event_id"],
                time_str=new_time,
                date_str=new_date,
            )
            if ok:
                t_str = f" to {self._fmt_time(new_time)}" if new_time else ""
                d_str = f" on {self._fmt_date(new_date)}" if new_date else ""
                self.speak(
                    f"{mapping.get('title', title_hint)} rescheduled{t_str}{d_str}. Calendar updated."
                )
            else:
                self.speak("Couldn't update the event. Calendar error.")
        except Exception as e:
            self.speak(f"Calendar error: {e}")
        return True

    def _add_reminder(self, d: dict, cmd: str) -> bool:
        task      = (d.get("reminder_task") or "").strip()
        time_expr = (d.get("reminder_time") or "").strip()

        if not task:
            self.speak("What should I remind you about?")
            return True
        if not time_expr:
            self.speak(f"At what time should I remind you to {task}?")
            return True

        try:
            result = self.scheduler.add_reminder(task, time_expr)
            self.speak(result)
        except Exception as e:
            self.speak(f"Couldn't set reminder: {e}")
        return True

    def _list_reminders(self, d: dict, cmd: str) -> bool:
        try:
            result = self.scheduler.list_reminders()
            self.speak(result)
        except Exception as e:
            self.speak(f"Couldn't list reminders: {e}")
        return True

    def _set_alarm(self, d: dict, cmd: str) -> bool:
        hour   = d.get("alarm_hour")
        minute = d.get("alarm_minute")

        # Fallback: try regex if LLM didn't extract time
        if hour is None:
            m = re.search(r'(\d{1,2}):(\d{2})', cmd)
            if m:
                hour, minute = int(m.group(1)), int(m.group(2))
            else:
                m = re.search(r'(\d{1,2})\s*(am|pm)', cmd, re.IGNORECASE)
                if m:
                    hour   = int(m.group(1))
                    suffix = m.group(2).lower()
                    if suffix == "pm" and hour != 12:
                        hour += 12
                    elif suffix == "am" and hour == 12:
                        hour = 0
                    minute = 0

        if hour is None:
            self.speak("Please specify a time for the alarm, like 7:30 AM.")
            return True

        minute = int(minute) if minute is not None else 0
        hour   = int(hour)

        try:
            import modules.system_control as _sc
            _, msg = _sc.set_alarm(hour, minute, self.speak)
            self.speak(msg)
        except Exception as e:
            self.speak(f"Couldn't set alarm: {e}")
        return True

    def _clear_calendar(self, d: dict, cmd: str) -> bool:
        try:
            from modules.calendar_agent import get_upcoming_events, cancel_event
            events = get_upcoming_events(hours=168)  # 7 days
            if not events:
                self.speak("Your calendar is already empty.")
                return True
            count = 0
            for e in events:
                try:
                    cancel_event(e["calendar_event_id"])
                    count += 1
                except Exception:
                    pass
            self.speak(
                f"Removed {count} event{'s' if count != 1 else ''} from your calendar."
            )
        except Exception as e:
            self.speak(f"Calendar error: {e}")
        return True
