const KEY = "desk-chats";
const EXAMPLES = [
  "How is a KERN ID assigned, and can it change?",
  "Can an account have two parents?",
  "Which fields does Kernel write to Salesforce?"
];
const GROUPS = [
  { id: "wrong_answer", title: "Wrong answer", short: "wrong answer", icon: "ph-x-circle" },
  { id: "should_have_refused", title: "Should have refused", short: "should have refused", icon: "ph-hand-palm" },
  { id: "incomplete", title: "Incomplete", short: "incomplete", icon: "ph-circle-half" },
  { id: "docs_gap", title: "Docs don't cover this", short: "docs gap", icon: "ph-file-dashed" }
];
const KINDS = [
  ["in_scope", "Answerable"],
  ["ambiguous", "Ambiguous"],
  ["out_of_scope", "Out of scope"]
];
const SAMPLES = [
  {
    id: "sample-answered",
    title: "Can an account have two parents?",
    turns: [
      { role: "user", text: "Can an account have two parents?" },
      {
        role: "assistant",
        open: false,
        steps: [{ id: "a1", text: "Looking through Parent relationships" }, { id: "a2", text: "Looking through KERN ID" }],
        data: {
          answer: "No. An account has a single immediate parent, the entity one level above it. Kernel also names a top parent and a top operating parent, and each of those is one entity. The account sits in one place in the tree, or it stands at the top with no parent.",
          citations: [{
            heading: "Parent relationships",
            url: "https://docs.kernel.ai/data/hierarchies/parent-relationships.md",
            quote: "The parent entity one level above the account. It is empty when the entity is standalone.",
            verified: true
          }],
          reaction: "helped"
        }
      }
    ]
  },
  {
    id: "sample-incomplete",
    title: "Which fields does Kernel write to Salesforce?",
    turns: [
      { role: "user", text: "Which fields does Kernel write to Salesforce?" },
      {
        role: "assistant",
        open: false,
        steps: [],
        data: {
          answer: "Kernel writes the KERN ID onto the Salesforce account.",
          citations: [],
          reaction: "not_helpful"
        }
      }
    ]
  },
  {
    id: "sample-refused",
    title: "How many days of holiday do Kernel employees get?",
    turns: [
      { role: "user", text: "How many days of holiday do Kernel employees get each year?" },
      {
        role: "assistant",
        open: false,
        steps: [{ id: "c1", text: "Nothing in the docs matched" }],
        data: {
          answer: "",
          clarifying_question: "Which office are you asking about?",
          citations: [],
          reaction: "not_helpful"
        }
      }
    ]
  },
  {
    id: "sample-gap",
    title: "What is Kernel's price per account?",
    turns: [
      { role: "user", text: "What is Kernel's price per account enrichment on our contract?" },
      {
        role: "assistant",
        open: false,
        steps: [{ id: "d1", text: "The docs don't cover this" }],
        data: {
          answer: "Kernel's public documentation does not contain pricing or contract cost information. To find the price per account enrichment on your contract, contact your Kernel account manager or review your signed service agreement.",
          abstain: true,
          citations: [],
          reaction: "not_helpful"
        }
      }
    ]
  }
];

const screenEl = document.querySelector("#screen");
const badge = document.querySelector("#badge");
let screen = screenFromPath();
let activeId = null;
let chats = loadChats();
let draft = "";
let busy = false;
let review = null;
let bulk = null;
let runId = "after";
let stampIndex = null;

document.querySelectorAll(".nav a").forEach(link => {
  if (link.dataset.screen === screen) link.setAttribute("aria-current", "page");
});

boot();

async function boot() {
  await attachLive();
  render();
  refreshBadge();
  if (screen === "review") await loadReview();
  if (screen === "bulk") await loadBulk();
}

function screenFromPath() {
  if (location.pathname.startsWith("/about")) return "about";
  if (location.pathname.startsWith("/bulk")) return "bulk";
  if (location.pathname.startsWith("/review") || location.pathname.startsWith("/suite")) return "review";
  return "ask";
}

function loadChats() {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(KEY) || "null");
    const saved = parsed && Array.isArray(parsed.chats) ? parsed.chats.filter(item => !isSample(item)) : [];
    const merged = saved.concat(SAMPLES);
    const savedActive = parsed && parsed.activeId;
    if (savedActive && saved.some(item => item.id === savedActive)) activeId = savedActive;
    else activeId = null;
    return merged;
  } catch (error) {
    activeId = null;
    return SAMPLES.slice();
  }
}

async function attachLive() {
  const sessions = chats.map(chat => ({
    id: chat.id,
    title: chat.title || "",
    turns: pairs(chat).filter(pair => pair.turn && !pair.turn.pending && !pair.turn.error).map(pair => {
      const data = pair.turn.data || {};
      return {
        question: pair.question,
        answer: data.answer || "",
        clarifying_question: data.clarifying_question || "",
        abstain: !!data.abstain,
        reason: data.reason || "",
        citations: (data.citations || []).map(cite => ({ chunk_id: cite.chunk_id || "", quote: cite.quote || "" }))
      };
    })
  })).filter(item => item.id && item.turns.length);
  if (!sessions.length) return;
  try {
    await fetch("/api/sessions/attach", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessions })
    });
  } catch (error) {
    // The transcript stays in this tab. The next send starts a fresh server session.
  }
}

function isSample(chat) {
  return !!chat && String(chat.id || "").indexOf("sample-") === 0;
}

function saveChats() {
  sessionStorage.setItem(KEY, JSON.stringify({
    chats: chats.filter(item => !isSample(item)),
    activeId,
    fresh: activeId === null
  }));
}

function render() {
  document.querySelector(".app").classList.toggle("is-about", screen === "about");
  if (screen === "ask") renderAsk();
  else if (screen === "review") renderReview();
  else if (screen === "about") renderAbout();
  else renderBulk();
}

function renderAbout() {
  document.title = "About the agent";
  screenEl.replaceChildren();
  const page = el("article", "about");
  page.innerHTML = `
    <div class="about-inner">
      <div class="about-lead">
        <div class="card-kicker">About this build</div>
        <h1>A docs agent, a complaint, and a recorded check</h1>
        <p>This is a support desk over Kernel's public docs, built as a portfolio piece. It is not Kernel's product and is not affiliated with Kernel. No support team has used it. The questions I checked it on were written from the docs, and it does not read Kernel account data.</p>
        <p>A customer asks a question. The agent looks the answer up itself and cites the passage, or says the docs don't cover it. If a reply did not help, a person labels it. Separately, the same agent was checked on a fixed set of questions, and those checks are recorded and graded in code. Labelling a complaint does not create a test and does not change the score.</p>
      </div>
      <section>
        <h2><i></i>Ask the docs</h2>
        <p>This screen is for a customer. They don't know the right answer and they don't type one.</p>
        <p>The agent reads the live docs at docs.kernel.ai and chooses its own lookups. While it works, a line names the section it is in, such as "Looking through KERN ID", and the line closes when the answer is ready. The answer sits with the passages it used. Each citation is the section, a link to the live page and the quoted words. If those words are not in the passage the model was given, the citation is marked. A follow-up question has its own citations.</p>
        <p>Under each reply the customer can press <strong>This helped</strong> or <strong>This didn't help</strong>. Helped stays on the page. Didn't help sends the question and the answer to Review.</p>
        <p>The conversation lives in this browser tab. A refresh keeps it, and closing the tab clears it. The server may keep a log of questions and tool calls for debugging, so don't type anything private. Four example conversations are already on the page: an ordinary answer, an incomplete answer, one that should have refused, and one the docs don't cover.</p>
      </section>
      <section>
        <h2><i></i>Review</h2>
        <p>A complaint arrives only when a customer presses <strong>This didn't help</strong>. Nothing is labelled automatically.</p>
        <p>The top line shows how many are waiting and how many are labelled. Under it are four counts: wrong answer, should have refused, incomplete, and docs don't cover this. The six labelled items on the demo are examples I filed to show the screen. They are not customer reports.</p>
        <p>Each waiting item shows the question, the answer and four buttons:</p>
        <div class="routes">
          <div class="route"><b><i class="ph ph-x-circle"></i>Wrong answer</b><span>Goes to the person who looks after the agent.</span></div>
          <div class="route"><b><i class="ph ph-circle-half"></i>Incomplete</b><span>Goes to the person who looks after the agent. The reply is on the right topic and still leaves out part of what was asked.</span></div>
          <div class="route"><b><i class="ph ph-hand-palm"></i>Should have refused</b><span>Goes to the person who looks after the agent.</span></div>
          <div class="route"><b><i class="ph ph-file-dashed"></i>Docs don't cover this</b><span>Goes to the person who looks after the docs.</span></div>
        </div>
        <p>One click files it. The label doesn't ask for the right answer, doesn't add a test case and doesn't run any check again. How a team turns labelled complaints into tests is their decision, and this demo stops at routing.</p>
      </section>
      <section>
        <h2><i></i>Bulk run</h2>
        <p>This screen is the recorded check, not the complaint queue. These are runs I did by hand while building. They are not an automatic rerun after every edit.</p>
        <div class="scores">
          <div class="score"><span>First run</span><em><b>14</b><small>of 26</small></em><p>Before the refusal and search fixes.</p></div>
          <div class="score"><span>After the fixes</span><em><b>19 to 20</b><small>of 26</small></em><p>Three runs scored 19, 20 and 19 of 26.</p></div>
          <div class="score on"><span>Held out</span><em><b>2</b><small>of 6</small></em><p>On six questions the agent had never been run against. This is the number to trust, because I tuned the agent against the other 26.</p></div>
        </div>
        <p>Each run is split into answerable, ambiguous and out-of-scope questions. Every row is Pass or Fail, and a failure shows its reason in one line. The grader is code that checks for required phrases, correct citations and refusals. No second model grades the first.</p>
        <p>The questions shown on screen belong to the run that is selected. They are not a new run.</p>
      </section>
      <section>
        <h2><i></i>What the check caught</h2>
        <p>The first catch was a citation, not a wrong fact. Asked what identity mode does when a record is ambiguous, the agent named the right idea and attached a quote that stitched several lines of the page into one passage. The words were on the page, but they were not one passage of the text the model was given. The check rejected the quote, and I didn't loosen the rule.</p>
      </section>
      <section>
        <h2><i></i>What still fails</h2>
        <div class="misses">
          <div><i class="ph ph-x"></i><span>Three questions failed on every run: identity mode, S3 versus the API, and the compensation question, where the agent asks a clarifying question instead of refusing.</span></div>
          <div><i class="ph ph-x"></i><span>The check looks for exact phrases, so a correct answer worded differently can fail. Two of the six held-out answers were right in substance and failed for that reason.</span></div>
          <div><i class="ph ph-x"></i><span>The 26 questions and the agent were tuned against each other, then frozen. I didn't rewrite a required fact after seeing results. Identity mode was added by hand before complaints and tests were separated. New complaints are not added to the 26.</span></div>
        </div>
      </section>
      <div><a class="btn btn-primary" href="/"><i class="ph ph-arrow-left"></i>Back to the app</a></div>
    </div>`;
  screenEl.appendChild(page);
}

function renderAsk() {
  const chat = chats.find(item => item.id === activeId);
  screenEl.replaceChildren();
  const wrap = el("div", "ask");
  const aside = el("aside", "history");
  const fresh = button("btn btn-secondary", "<i class=\"ph ph-plus\"></i>New chat");
  fresh.style.justifyContent = "flex-start";
  fresh.style.width = "100%";
  fresh.addEventListener("click", () => { activeId = null; draft = ""; saveChats(); renderAsk(); });
  const list = el("div");
  list.appendChild(el("div", "kicker", "Conversations"));
  if (!chats.length) list.appendChild(el("div", "quiet", "No chats in this browser yet."));
  chats.forEach(item => {
    const row = button("chat-btn" + (item.id === activeId ? " active" : ""));
    row.innerHTML = "<i class=\"ph ph-chat-circle-text\"></i><span></span>";
    row.querySelector("span").textContent = item.title || "New chat";
    row.addEventListener("click", () => { activeId = item.id; saveChats(); renderAsk(); });
    list.appendChild(row);
  });
  aside.append(fresh, list);

  const main = el("main", "stage");
  const thread = el("div", "thread");
  const inner = el("div", "thread-inner");
  if (!chat) inner.appendChild(emptyState());
  else inner.appendChild(conversation(chat));
  thread.appendChild(inner);
  main.append(thread, composer());
  wrap.append(aside, main);
  screenEl.appendChild(wrap);
  if (busy) thread.scrollTop = thread.scrollHeight;
}

function emptyState() {
  const block = el("div", "empty");
  const copy = el("div", "empty-copy");
  copy.append(el("h1", "", "Ask the docs"), el("p", "", "Ask a question about Kernel's docs. The agent looks it up and cites the passage, or says the docs don't cover it."));
  const examples = el("div", "examples");
  EXAMPLES.forEach(text => {
    const pick = button("btn btn-secondary");
    const label = el("span", "", text);
    pick.append(label, icon("ph-arrow-down-left"));
    pick.addEventListener("click", () => {
      draft = text;
      const box = document.querySelector("#draft");
      if (box) { box.value = text; box.focus(); syncSend(); }
    });
    examples.appendChild(pick);
  });
  block.append(copy, examples);
  return block;
}

function conversation(chat) {
  const block = el("div", "convo");
  pairs(chat).forEach(pair => block.appendChild(message(chat, pair)));
  return block;
}

function pairs(chat) {
  const rows = [];
  let question = "";
  (chat.turns || []).forEach(turn => {
    if (turn.role === "user") question = turn.text;
    else rows.push({ question, turn });
  });
  return rows;
}

function message(chat, pair) {
  const turn = pair.turn;
  const data = turn.data || {};
  const wrap = el("div", "turn");
  const you = el("div", "you");
  you.append(el("span", "eyebrow", "You"), el("div", "you-bubble", pair.question));
  const agent = el("div", "agent");
  const who = el("div", "agent-label eyebrow");
  who.append(el("span", "dot"), document.createTextNode("Docs agent"));
  agent.appendChild(who);

  if (turn.pending) {
    turn.open = true;
    agent.appendChild(lookup(turn, lookupLines(turn), true));
  } else if (turn.error) {
    agent.appendChild(el("div", "answer", turn.error));
  } else {
    const lines = lookupLines(turn);
    if (lines.length) agent.appendChild(lookup(turn, lines));
    const answer = el("div", "answer");
    if (data.abstain) answer.appendChild(tag("tag tag-neutral", "ph-file-dashed", "Not in the docs"));
    paragraphs(shown(data)).forEach(text => answer.appendChild(el("p", "", text)));
    agent.appendChild(answer);
    const cites = data.citations || [];
    if (cites.length) agent.appendChild(citations(cites));
    if (data.reaction === "helped") agent.appendChild(status("ph-check-circle", "Glad it helped."));
    else if (data.reaction === "not_helpful") agent.appendChild(status("ph-tray-arrow-up", "Thanks for telling us. We'll look into that reply."));
    else agent.appendChild(feedback(chat, turn, pair.question, shown(data)));
  }
  wrap.append(you, agent);
  return wrap;
}

function lookup(turn, lines, live) {
  const box = el("div");
  const toggle = button("lookup");
  toggle.append(icon("ph-books"), el("span", "", lookedThrough(lines)), icon(turn.open ? "ph-caret-up" : "ph-caret-down"));
  if (!live) toggle.addEventListener("click", () => { turn.open = !turn.open; saveChats(); renderAsk(); });
  box.appendChild(toggle);
  if (turn.open) {
    const list = el("div", "lookup-lines");
    lines.forEach((text, index) => {
      const row = el("div");
      row.append(el("span", "", String(index + 1).padStart(2, "0")));
      if (live && index === lines.length - 1) row.append(icon("ph-circle-notch spin"));
      row.append(document.createTextNode(text));
      list.appendChild(row);
    });
    box.appendChild(list);
  }
  return box;
}

function citations(cites) {
  const block = el("div", "cites");
  block.appendChild(el("div", "eyebrow", "Citations · this answer"));
  cites.forEach((cite, index) => {
    const row = el("div", "cite");
    row.appendChild(el("span", "cite-n", String(index + 1)));
    const body = el("div");
    const head = el("div");
    head.style.display = "flex";
    head.style.gap = "10px";
    head.style.flexWrap = "wrap";
    head.style.alignItems = "center";
    if (cite.url) {
      const link = document.createElement("a");
      link.href = cite.url.replace(/\.md$/, "");
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = cite.heading || cite.url;
      link.appendChild(icon("ph-arrow-up-right"));
      head.appendChild(link);
    }
    if (cite.verified === false) head.appendChild(tag("tag tag-outline", "ph-warning", "Quote not in that section"));
    const quote = document.createElement("q");
    quote.textContent = cite.quote || "";
    if (cite.verified === false) quote.className = "bad";
    body.append(head, quote);
    row.appendChild(body);
    block.appendChild(row);
  });
  return block;
}

function feedback(chat, turn, question, answer) {
  const row = el("div", "feedback");
  const helped = button("btn btn-secondary btn-feedback", "<i class=\"ph ph-thumbs-up\"></i>This helped");
  const missed = button("btn btn-secondary btn-feedback", "<i class=\"ph ph-thumbs-down\"></i>This didn't help");
  helped.addEventListener("click", () => { turn.data.reaction = "helped"; saveChats(); renderAsk(); });
  missed.addEventListener("click", () => sendReview(chat, turn, question, answer));
  row.append(helped, missed);
  return row;
}

async function sendReview(chat, turn, question, answer) {
  const response = await fetch("/api/review", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, answer })
  });
  if (!response.ok) return;
  turn.data.reaction = "not_helpful";
  saveChats();
  review = null;
  renderAsk();
  refreshBadge();
}

function composer() {
  const bar = el("div", "composer");
  const inner = el("div", "composer-inner");
  const prompt = el("div", "prompt");
  const box = document.createElement("textarea");
  box.id = "draft";
  box.rows = 2;
  box.placeholder = "Ask about a KERN ID, a parent, the API, or Salesforce";
  box.value = draft;
  box.addEventListener("input", () => { draft = box.value; syncSend(); });
  box.addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); send(); }
  });
  const sendBtn = button("btn btn-primary", "<span>Send</span><i class=\"ph ph-arrow-up\"></i>");
  sendBtn.id = "send";
  sendBtn.addEventListener("click", send);
  prompt.append(box, sendBtn);
  const hint = el("div", "hint");
  hint.append(document.createTextNode("Read more about the agent and the eval loop "));
  const link = document.createElement("a");
  link.href = "/about";
  link.textContent = "here";
  hint.append(link, document.createTextNode("."));
  inner.append(prompt, hint);
  bar.appendChild(inner);
  queueMicrotask(syncSend);
  return bar;
}

function syncSend() {
  const sendBtn = document.querySelector("#send");
  if (sendBtn) sendBtn.disabled = busy || !draft.trim();
}

async function send() {
  const text = draft.trim();
  if (!text || busy) return;
  busy = true;
  draft = "";
  let chat = chats.find(item => item.id === activeId);
  if (!chat) {
    chat = { id: crypto.randomUUID(), title: text.length > 42 ? text.slice(0, 42).trimEnd() + "…" : text, turns: [] };
    activeId = chat.id;
    chats.unshift(chat);
  }
  chat.turns.push({ role: "user", text });
  const pending = { role: "assistant", pending: true, liveLine: "Looking through the docs", steps: [], data: {} };
  chat.turns.push(pending);
  chats = [chat, ...chats.filter(item => item.id !== chat.id)];
  saveChats();
  renderAsk();
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: activeId, message: text })
    });
    const type = response.headers.get("content-type") || "";
    if (!response.ok || !type.includes("text/event-stream")) {
      const data = await response.json();
      throw new Error(data.error || "Request failed");
    }
    const final = await readEvents(response, pending);
    if (final.conversation_id && final.conversation_id !== chat.id) {
      chat.id = final.conversation_id;
      activeId = chat.id;
    }
    delete pending.pending;
    pending.data = final;
    pending.open = false;
    saveChats();
  } catch (error) {
    const index = chat.turns.indexOf(pending);
    if (index >= 0) chat.turns.splice(index, 1, { role: "assistant", error: error.message });
    saveChats();
  } finally {
    busy = false;
    renderAsk();
    const box = document.querySelector("#draft");
    if (box) box.focus();
  }
}

async function readEvents(response, pending) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let final = null;
  while (true) {
    const chunk = await reader.read();
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop();
    for (const part of parts) {
      const line = part.split("\n").find(item => item.startsWith("data: "));
      if (!line) continue;
      const event = JSON.parse(line.slice(6));
      if (event.type === "step") {
        const known = pending.steps.find(step => step.id === event.id);
        if (known) Object.assign(known, event);
        else pending.steps.push(event);
        renderAsk();
        await new Promise(resolve => requestAnimationFrame(resolve));
      } else if (event.type === "error") throw new Error(event.error || "Request failed");
      else if (event.type === "final") final = event;
    }
  }
  if (!final) throw new Error("The reply ended before an answer was ready.");
  return final;
}

async function refreshBadge() {
  try {
    const data = await (await fetch("/api/review")).json();
    review = data;
    badge.hidden = !data.waiting;
    badge.textContent = data.waiting || "";
  } catch (error) {
    badge.hidden = true;
  }
}

async function loadReview() {
  review = await (await fetch("/api/review")).json();
  badge.hidden = !review.waiting;
  badge.textContent = review.waiting || "";
  if (screen === "review") renderReview();
}

function renderReview() {
  screenEl.replaceChildren();
  const page = el("div", "page");
  const inner = el("div", "page-inner");
  if (!review) {
    inner.appendChild(el("p", "lede", "Loading…"));
    page.appendChild(inner);
    screenEl.appendChild(page);
    return;
  }
  const head = el("div", "page-head");
  head.append(el("div", "card-kicker", "Complaints"), el("h1", "", "Review"), el("p", "lede", "This page is for reviewers. A complaint arrives when a customer says a reply did not help. Label it so it reaches the person who should fix that kind of problem."));
  const counts = el("div", "counter-row");
  counts.appendChild(el("span", "counter", review.waiting + " waiting, " + review.labelled + " labelled."));
  head.append(counts, kpiRow());

  const waiting = el("section", "block");
  const title = el("div", "block-title");
  title.append(el("h2", "", "Waiting"), tag("tag tag-accent", "", String(review.waiting)));
  waiting.appendChild(title);
  const items = review.items.filter(item => !item.label_id);
  if (!items.length) {
    const empty = el("div", "empty-box");
    const copy = el("p");
    const ask = document.createElement("a");
    ask.href = "/";
    ask.textContent = "Ask the docs";
    copy.append(
      document.createTextNode("Nothing is waiting. Ask a question on "),
      ask,
      document.createTextNode(" and press "),
      didntHelpBubble(),
      document.createTextNode(" on the reply. The question and the answer show up here.")
    );
    empty.appendChild(copy);
    waiting.appendChild(empty);
  }
  items.forEach(item => waiting.appendChild(ticket(item)));

  const labelled = el("section", "block");
  labelled.appendChild(el("h2", "", "Labelled"));
  const grid = el("div", "groups");
  GROUPS.forEach(group => {
    const info = review.labels[group.id];
    const column = el("div");
    column.style.display = "flex";
    column.style.flexDirection = "column";
    column.style.gap = "14px";
    const headRow = el("div", "group-head");
    const name = el("div", "group-title");
    const label = el("span");
    label.append(icon(group.icon), document.createTextNode(group.title));
    name.append(label, el("b", "", String(review.counts[group.id] || 0)));
    headRow.append(name, el("div", "group-owner", info.owner));
    column.appendChild(headRow);
    const mine = review.items.filter(item => item.label_id === group.id);
    if (!mine.length) column.appendChild(el("div", "ghost-box", "Empty. Complaints labelled here go to " + info.owner.charAt(0).toLowerCase() + info.owner.slice(1) + "."));
    mine.forEach(item => {
      const card = el("div", "card labelled");
      card.append(el("span", "q", item.question), el("span", "a", item.answer));
      const goes = el("span", "goes");
      goes.append(icon("ph-arrow-bend-down-right"), document.createTextNode("Goes to " + info.owner.charAt(0).toLowerCase() + info.owner.slice(1)));
      card.appendChild(goes);
      column.appendChild(card);
    });
    grid.appendChild(column);
  });
  labelled.appendChild(grid);
  inner.append(head, waiting, labelled);
  page.appendChild(inner);
  screenEl.appendChild(page);
}

function didntHelpBubble() {
  const bubble = el("span", "btn btn-secondary in-sentence");
  bubble.innerHTML = "<i class=\"ph ph-thumbs-down\"></i>This didn't help";
  return bubble;
}

function kpiRow() {
  const row = el("div", "kpis");
  const total = review.labelled || 0;
  GROUPS.forEach(group => {
    const count = review.counts[group.id] || 0;
    const tile = el("div", "kpi");
    const name = el("span");
    name.append(icon(group.icon), document.createTextNode(group.title));
    const track = el("div", "kpi-bar");
    const fill = el("span");
    fill.style.width = (total ? Math.round((count / total) * 100) : 0) + "%";
    track.appendChild(fill);
    tile.append(el("b", "", String(count)), name, track);
    row.appendChild(tile);
  });
  return row;
}

function ticket(item) {
  const card = el("div", "card elev-sm ticket");
  const qa = el("div", "qa");
  qa.append(el("span", "eyebrow", "Question"), el("span", "", item.question), el("span", "eyebrow", "Answer"), el("span", "ans", item.answer));
  const actions = el("div", "ticket-actions");
  GROUPS.forEach(group => {
    const control = button("btn btn-secondary", "<i class=\"ph " + group.icon + "\"></i>" + group.title);
    control.style.fontSize = "13px";
    control.addEventListener("click", () => labelItem(item.id, group.id));
    actions.appendChild(control);
  });
  card.append(qa, actions);
  return card;
}

async function labelItem(id, kind) {
  const response = await fetch("/api/review/label", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, label: kind })
  });
  if (!response.ok) return;
  review = (await response.json()).summary;
  badge.hidden = !review.waiting;
  badge.textContent = review.waiting || "";
  renderReview();
}

async function loadBulk() {
  bulk = await (await fetch("/api/bulk")).json();
  if (stampIndex === null) {
    const after = bulk.runs.find(item => item.id === "after");
    stampIndex = after ? after.stamps.length - 1 : 0;
  }
  if (screen === "bulk") renderBulk();
}

function renderBulk() {
  screenEl.replaceChildren();
  const page = el("div", "page");
  const inner = el("div", "page-inner");
  inner.style.gap = "44px";
  if (!bulk) {
    inner.appendChild(el("p", "lede", "Loading…"));
    page.appendChild(inner);
    screenEl.appendChild(page);
    return;
  }
  const head = el("div", "page-head");
  head.append(
    el("div", "card-kicker", "Recorded suite"),
    el("h1", "", "Bulk run"),
    el("p", "lede", "This page is the recorded test of the agent. It is separate from customer conversations and from Review. First run is 14 of 26, from 8 October 2026, before the refusal and search fixes. After fixes is three passes that morning, scoring 19 to 20 of 26. Held out is 2 of 6, on questions the agent had not been run against. The held-out result is the one to trust.")
  );
  const cards = el("div", "runs");
  bulk.runs.forEach(run => {
    const control = button("run" + (run.id === runId ? " on" : ""));
    const top = el("div", "run-top");
    top.append(el("span", "", run.title), el("small", "", run.stamps.length > 1 ? "3 passes" : when(run.stamps[0].run_at)));
    const score = splitScore(run.score);
    const numbers = el("div", "run-score");
    numbers.append(el("b", "", score.big), el("span", "", score.small));
    control.append(top, numbers, el("p", "", runNote(run)));
    control.addEventListener("click", () => { runId = run.id; renderBulk(); });
    cards.appendChild(control);
  });

  const run = bulk.runs.find(item => item.id === runId) || bulk.runs[0];
  const index = run.stamps.length > 1 ? Math.min(stampIndex, run.stamps.length - 1) : 0;
  const stamp = run.stamps[index];
  const bar = el("div", "passbar");
  const row = el("div", "pass-row");
  if (run.stamps.length > 1) {
    const seg = el("div", "seg");
    run.stamps.forEach((item, itemIndex) => {
      const option = button("seg-opt" + (itemIndex === index ? " on" : ""));
      option.append(document.createTextNode(when(item.run_at)), el("span", "", item.passed + " of " + item.total));
      option.addEventListener("click", () => { stampIndex = itemIndex; renderBulk(); });
      seg.appendChild(option);
    });
    row.appendChild(seg);
  }
  const passed = stamp.cases.filter(item => item.passed).length;
  row.appendChild(el("span", "pass-caption", (run.stamps.length > 1 ? "Showing pass " + when(stamp.run_at) : "Pass " + when(stamp.run_at)) + " · " + passed + " of " + stamp.cases.length + " passed"));
  const strip = el("div", "strip");
  stamp.cases.forEach(item => {
    const tick = document.createElement("i");
    if (item.passed) tick.className = "ok";
    tick.title = (item.passed ? "Pass · " : "Fail · ") + item.question;
    strip.appendChild(tick);
  });
  bar.append(row, strip);

  const columns = el("div", "bulk-groups");
  KINDS.forEach(([kind, title]) => {
    const cases = stamp.cases.filter(item => item.kind === kind);
    const group = el("section", "bulk-group");
    const heading = el("h2", "", title);
    if (cases.length) heading.appendChild(el("span", "", cases.filter(item => item.passed).length + " of " + cases.length + " passed"));
    group.appendChild(heading);
    if (!cases.length) group.appendChild(el("div", "none", "None in this run."));
    else {
      const table = el("table", "table");
      const body = document.createElement("tbody");
      cases.forEach(item => {
        const tr = document.createElement("tr");
        if (!item.passed) tr.className = "fail";
        const mark = document.createElement("td");
        mark.appendChild(tag(item.passed ? "tag tag-accent" : "tag tag-neutral", "", item.passed ? "Pass" : "Fail"));
        const cell = document.createElement("td");
        const question = el("span", "q", item.question);
        cell.appendChild(question);
        if (!item.passed && item.reasons.length) cell.appendChild(el("span", "why", item.reasons.join("; ")));
        tr.append(mark, cell);
        body.appendChild(tr);
      });
      table.appendChild(body);
      group.appendChild(table);
    }
    columns.appendChild(group);
  });
  inner.append(head, cards, bar, columns);
  page.appendChild(inner);
  screenEl.appendChild(page);
}

function runNote(run) {
  if (run.id === "after") return "Three passes after the fixes. The score moved between 19 and 20. The questions on screen are the pass that is selected, not a new run.";
  if (run.id === "held") return "Six questions the agent had not been run against. This is the number to trust.";
  return "One pass over the 26 questions, before the refusal and search fixes. Graded in code.";
}

function splitScore(score) {
  const match = String(score).match(/^(.*)\s+(of\s+\d+)$/);
  return match ? { big: match[1], small: match[2] } : { big: score, small: "" };
}

function sectionName(name) {
  const trimmed = String(name || "").replace(/[-–—]+/g, " ").replace(/\s+/g, " ").trim();
  if (!trimmed || trimmed === "the docs") return false;
  if (/[{}=<>]|->/.test(name)) return false;
  if (/^[a-z0-9]/.test(trimmed)) return false;
  return true;
}

function lookupLines(turn) {
  const lines = [];
  (turn.steps || []).forEach(step => {
    const text = (step.text || "").trim();
    if (!text || text === "Looking through the docs") return;
    if (text === "The docs don't cover this" || text === "Nothing in the docs matched") {
      if (!lines.includes(text)) lines.push(text);
      return;
    }
    if (text.startsWith("Looking through ") && sectionName(text.slice("Looking through ".length))) {
      if (!lines.includes(text)) lines.push(text);
    }
  });
  if (lines.length) return lines;
  const seen = new Set();
  ((turn.data && turn.data.citations) || []).forEach(cite => {
    const name = cite.heading || cite.title || "";
    if (name && !seen.has(name)) {
      seen.add(name);
      lines.push("Looking through " + name);
    }
  });
  if (!lines.length && turn.pending) return ["Looking through the docs"];
  return lines;
}

function lookedThrough(lines) {
  const names = [];
  lines.forEach(line => {
    const name = line.replace(/^Looking through /, "");
    if (line.startsWith("Looking through ") && name && !names.includes(name)) names.push(name);
  });
  if (!names.length) return lines[0];
  if (names.length === 1) return "Looked through " + names[0];
  if (names.length === 2) return "Looked through " + names[0] + " and " + names[1];
  return "Looked through " + names[0] + " and " + (names.length - 1) + " other sections";
}

function shown(data) {
  const text = data.clarifying_question && !data.answer ? data.clarifying_question : (data.answer || data.reason || "");
  return String(text)
    .replace(/\s*\(\s*chunk_id\s*:\s*[A-Za-z0-9]+\s*\)/gi, "")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/ +([.,;:])/g, "$1")
    .trim();
}

function paragraphs(text) {
  const blocks = String(text || "").split(/\n{2,}/).map(item => item.trim()).filter(Boolean);
  return blocks.length ? blocks : [""];
}

function when(value) {
  const date = new Date(value);
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return date.getUTCDate() + " " + months[date.getUTCMonth()] + " " + String(date.getUTCHours()).padStart(2, "0") + ":" + String(date.getUTCMinutes()).padStart(2, "0") + " UTC";
}

function status(glyph, text) {
  const row = el("div", "note");
  row.append(icon(glyph), document.createTextNode(text));
  return row;
}

function tag(className, glyph, text) {
  const node = el("span", className);
  if (glyph) node.appendChild(icon(glyph));
  node.appendChild(document.createTextNode(text));
  return node;
}

function icon(className) {
  const node = document.createElement("i");
  node.className = "ph " + className;
  return node;
}

function button(className, html) {
  const node = document.createElement("button");
  node.type = "button";
  node.className = className;
  if (html) node.innerHTML = html;
  return node;
}

function el(tagName, className, text) {
  const node = document.createElement(tagName);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}
