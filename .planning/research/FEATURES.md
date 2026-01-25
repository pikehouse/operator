# Features Research: TUI Demo

**Domain:** Live TUI dashboard for distributed system monitoring demo
**Researched:** 2026-01-24
**Confidence:** MEDIUM (based on established TUI patterns, verified against popular tools)

## Table Stakes

Features users expect from any TUI dashboard showing multiple running processes. Missing any of these makes the demo feel incomplete or unprofessional.

### Layout and Structure

- **Multi-panel layout with clear boundaries** - Separate visual regions for different data streams
  - Complexity: Low
  - Why essential: Users expect dashboards to show multiple data streams simultaneously. A single scrolling output is not a "dashboard" - it's just a log. Panels create the mental model of "I can monitor multiple things at once."

- **Real-time updates without flicker** - Smooth 1-2 second refresh with diff-based rendering
  - Complexity: Low (Rich Live handles this)
  - Why essential: Flickering or jerky updates look broken. btop and k9s set the bar: data should flow smoothly. Rich Live already supports this.

- **Color-coded status indicators** - Green/yellow/red for healthy/warning/critical states
  - Complexity: Low
  - Why essential: Eye-tracking research shows color is processed faster than text. A green box that turns red immediately communicates "something changed" without reading. Standard in htop, btop, k9s, every monitoring tool.

- **Clear panel titles/headers** - Each panel must identify what it shows
  - Complexity: Low
  - Why essential: Users scan the F-pattern (top-left to right, then down). Panel titles orient them instantly. Without them, users waste time figuring out what they're looking at.

- **Responsive to terminal resize** - Layout adapts when terminal dimensions change
  - Complexity: Medium (Rich Layout handles most of this)
  - Why essential: Conference presenters resize terminals constantly. A demo that breaks on resize looks amateur.

### Process Visibility

- **Running daemon status indicators** - Show that monitor and agent are actually running
  - Complexity: Low
  - Why essential: The whole point of the TUI demo is "look, real daemons running." If users can't tell they're running, the demo fails its core purpose.

- **Activity indicators (heartbeat/spinner)** - Visual proof of liveness
  - Complexity: Low
  - Why essential: Static displays look frozen. A subtle pulse or spinner says "this is live, not a screenshot." k9s does this excellently with its refresh indicator.

- **Timestamp of last update** - When was this data refreshed?
  - Complexity: Low
  - Why essential: Removes ambiguity about freshness. Users need to know they're seeing current state, not cached data.

### System Health Display

- **Cluster status summary** - Overall health at a glance
  - Complexity: Low-Medium
  - Why essential: The primary question for any monitoring dashboard is "is everything okay?" This must be answerable in under 1 second. Aggregate status cards are a standard dashboard pattern.

- **Node count with health breakdown** - "3/3 nodes healthy" or "2/3 nodes healthy"
  - Complexity: Low
  - Why essential: For distributed systems, node count is the fundamental metric. It's what the demo is about - killing a node and watching the system respond.

### Keyboard Interaction

- **Key-press instructions visible** - Show available keyboard shortcuts
  - Complexity: Low
  - Why essential: TUIs are keyboard-driven. Users shouldn't have to guess what keys do what. A small footer with shortcuts is standard (btop, k9s, htop all do this).

- **Chapter/stage progression via keypress** - Demo narrator controls the pace
  - Complexity: Low-Medium
  - Why essential: Conference demos need controlled pacing. The presenter decides when to inject the fault, not an automatic timer. This enables dramatic timing.


## Differentiators

Features that make this demo stand out from a typical monitoring dashboard. These aren't expected, but create the "wow" moment for technical audiences.

### Live Process Output Capture

- **Real daemon output in dedicated panels** - Show actual monitor/agent logs as they happen
  - Complexity: Medium-High
  - Why impressive: Most demos run processes in the background with no visibility. Showing the actual output proves "this is really running" and lets the audience see the detection/diagnosis happen in real-time.

### Workload Visualization

- **Ops/sec histogram or sparkline** - Visual representation of traffic
  - Complexity: Medium
  - Why impressive: Turns abstract "load" into something visible. When the histogram drops or turns red after fault injection, the audience immediately understands the impact. More visceral than numbers.

- **Degradation color shift** - Workload panel color changes when performance degrades
  - Complexity: Low (once you have the data)
  - Why impressive: Visual correlation between "fault injected" and "workload suffered" is the narrative arc of the demo. Color shift makes this unmissable.

### Demo Narration

- **Chapter/stage panel with context** - "Chapter 2: Injecting Fault" with brief explanation
  - Complexity: Low
  - Why impressive: Guides the audience through the narrative. They know what they're supposed to be watching for. Reduces cognitive load and increases engagement.

- **Countdown timers for key moments** - "Detecting fault... 3s"
  - Complexity: Low
  - Why impressive: Builds tension. The audience is actively watching for detection. When it happens, there's satisfaction. This is presentation technique, not just engineering.

### AI Diagnosis Display

- **Structured diagnosis panel** - Show AI reasoning in formatted panel
  - Complexity: Low (already exists in current demo)
  - Why impressive: The core value prop - AI explaining what's happening with alternatives considered. Keeping this prominent in the TUI is essential.

- **Diagnosis appearing "live"** - Panel populates as AI responds
  - Complexity: Medium (streaming structured output)
  - Why impressive: Watching the diagnosis write itself is more engaging than seeing it appear all at once. It emphasizes that this is happening in real-time.

### Recovery Narrative

- **Before/after cluster state** - Show health transition: degraded -> healthy
  - Complexity: Low-Medium
  - Why impressive: Completes the story. The demo shouldn't just show failure detection - it should show the path to recovery. This demonstrates the full operator value.

### Technical Polish

- **Sub-second detection highlighting** - Flash or emphasize the moment detection occurs
  - Complexity: Low
  - Why impressive: The detection moment is the climax of the demo. A brief highlight (border flash, bold text) draws attention and creates a memorable moment.

- **Timeline/event log** - Chronological list of what happened
  - Complexity: Medium
  - Why impressive: For post-demo discussion: "At 12:34:05 we injected the fault, at 12:34:07 the monitor detected it, at 12:34:15 the diagnosis completed." Concrete timing demonstrates system responsiveness.


## Anti-Features

Things to deliberately NOT build. These either add complexity without value, or actively hurt the demo experience.

### Avoid: Scrolling log panels
- **Why not:** Scrolling logs are what the CLI already does. A TUI dashboard should synthesize information, not dump raw logs. If you need logs, use a separate terminal.

### Avoid: Mouse-driven navigation
- **Why not:** Conference demos happen with the presenter at a keyboard. Mouse interaction requires looking at the cursor, breaking eye contact with the audience. Keyboard-only is faster and more professional.

### Avoid: Configuration UI in the demo
- **Why not:** The demo should "just work." Any configuration UI adds points of failure and distracts from the core narrative. Pre-configure everything.

### Avoid: Multiple themes or customization
- **Why not:** One polished theme is better than five half-baked ones. Customization is engineering effort that doesn't improve the demo impact.

### Avoid: Persistent state between runs
- **Why not:** Each demo run should be fresh. Persistent state creates debugging nightmares when something "remembers" a previous failed run.

### Avoid: Too many panels (>6)
- **Why not:** Cognitive overload. If the audience can't process everything in 5 seconds, you have too much. btop succeeds with 4-5 focused areas. More isn't better.

### Avoid: Animations for animation's sake
- **Why not:** Subtle activity indicators are good. Gratuitous animations distract from the content. The demo content (AI diagnosis) should be the star, not the UI chrome.

### Avoid: Real-time metrics graphs with long history
- **Why not:** A 60-minute graph is useless in a 2-minute demo. Show only the relevant time window. If you need historical data, that's a different tool.


## Demo Flow Considerations

What makes a fault-injection demo compelling for technical audiences, based on chaos engineering presentation best practices.

### Narrative Structure

**Beginning (30-60 seconds):**
- Show the healthy state explicitly
- Establish baseline (all nodes up, workload flowing)
- This is the "before" that makes the "after" meaningful

**Middle (60-90 seconds):**
- Inject fault with visible action (not silent background)
- Build tension with detection countdown
- Show the impact (workload degradation)
- Climax: detection happens, AI begins diagnosis

**End (60-90 seconds):**
- Display AI diagnosis prominently
- Walk through the reasoning (alternatives considered)
- Show recovery or recommendation
- Return to healthy state (closure)

### Key Moments to Emphasize

1. **The Kill** - The moment of fault injection should be unmistakable. A visual cue (color change, banner) makes it clear "now the system is under stress."

2. **The Detection** - The moment the system notices should be highlighted. This is where the demo proves its value - fast, automatic detection.

3. **The Diagnosis** - The AI reasoning is the unique value. Give it screen real estate and let the audience read it.

### Pacing Considerations

- **Interactive pauses are good** - "Press Enter to inject fault" lets the presenter narrate, builds anticipation, and ensures the audience is ready.

- **Automatic progression is bad** - Timers that advance without presenter control are risky. What if the presenter needs to explain something? What if there's a question?

- **Detection should feel fast** - 2-4 second detection time is impressive. >10 seconds feels slow. If detection is slow, acknowledge it ("In production you'd configure more aggressive polling").

### Technical Audience Expectations

Technical audiences (conference talks, engineering demos) expect:

- **Honesty** - Don't hide errors or pretend things work when they don't. If something fails, acknowledge it.
- **Real systems** - They can tell the difference between a real cluster and mocked data. The docker-compose 6-node setup is credible.
- **Substantive AI output** - Not "something is wrong" but "here's what's happening, here's why, here's what to do." This is the existing demo's strength.
- **No sales pitches** - Technical audiences tune out marketing speak. Let the demo speak for itself.

### Recovery from Failure

Demos fail sometimes. Plan for it:

- **Graceful degradation** - If AI times out, show the context that would have been provided
- **Restart capability** - A single keypress should be able to restart the demo cleanly
- **Fallback narrative** - "As you can see, the detection worked; let me show you a pre-recorded diagnosis..."


## MVP Recommendation

For the v1.1 TUI demo, prioritize:

### Must Have (Table Stakes)
1. Multi-panel layout (cluster status, monitor output, agent output, narration)
2. Color-coded node health indicators
3. Key-press chapter progression
4. Real daemon output capture

### Should Have (High-Impact Differentiators)
5. Workload panel with degradation color
6. Detection moment highlighting
7. Chapter/narration panel

### Can Defer
- Timeline/event log
- Streaming diagnosis display
- Sparkline/histogram (simple bar may suffice)

The existing `operator demo chaos` already has the AI diagnosis quality. The TUI upgrade is about visibility into the running system and presentation polish, not new functionality.


## Sources

- [Building Rich Terminal Dashboards](https://www.willmcgugan.com/blog/tech/post/building-rich-terminal-dashboards/) - Rich layout patterns
- [Textual TUI Documentation](https://textual.textualize.io/) - Widget gallery and patterns
- [k9s - Kubernetes CLI and TUI](https://k9scli.io/) - Real-time cluster monitoring UX
- [btop - The htop Alternative](https://linuxblog.io/btop-the-htop-alternative/) - System monitoring dashboard patterns
- [Dashboard Design UX Patterns](https://www.pencilandpaper.io/articles/ux-pattern-analysis-data-dashboards) - F-pattern and card layout principles
- [How to Present Chaos Testing Effectively](https://www.resumly.ai/blog/how-to-present-chaos-testing-and-learnings-effectively) - Presentation narrative
- [How to Present to a Technical Audience](https://wlanprofessionals.com/how-to-present-to-a-technical-audience/) - Technical audience expectations
- [Live Demos Guide](https://www.arcade.software/post/live-demos-guide) - Demo preparation and execution
- [Microsoft Fault Injection Testing Playbook](https://microsoft.github.io/code-with-engineering-playbook/automated-testing/fault-injection-testing/) - Chaos engineering observability patterns
