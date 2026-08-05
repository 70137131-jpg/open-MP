/**
 * OpenMP / MPI online compiler - frontend controller.
 *
 * The page is served either by Flask (same origin as the API) or as a static
 * bundle with the API behind a proxy, so the API base is resolved at runtime.
 */
(function () {
  "use strict";

  var STORAGE_KEY = "openmp-compiler.state.v1";
  var HEALTH_INTERVAL_MS = 60000;
  var REQUEST_TIMEOUT_MS = 60000;

  var API_BASE =
    window.location.protocol === "file:" ? "http://localhost:5000" : window.location.origin;

  var el = {
    output: document.getElementById("output"),
    runBtn: document.getElementById("runBtn"),
    runBtnLabel: document.getElementById("runBtnLabel"),
    clearBtn: document.getElementById("clearBtn"),
    clearOutputBtn: document.getElementById("clearOutputBtn"),
    copyCodeBtn: document.getElementById("copyCodeBtn"),
    copyOutputBtn: document.getElementById("copyOutputBtn"),
    downloadBtn: document.getElementById("downloadBtn"),
    themeToggle: document.getElementById("themeToggle"),
    themeIcon: document.getElementById("themeIcon"),
    statusText: document.getElementById("statusText"),
    statusDot: document.getElementById("statusDot"),
    backendStatus: document.getElementById("backendStatus"),
    language: document.getElementById("languageSelect"),
    mode: document.getElementById("modeSelect"),
    workers: document.getElementById("workerSelect"),
    workerLabel: document.getElementById("workerLabel"),
    openmpExamples: document.getElementById("openmpExamples"),
    mpiExamples: document.getElementById("mpiExamples"),
    limitsBanner: document.getElementById("limitsBanner")
  };

  var examples = (window.OPENMP_EXAMPLES || []).slice();
  var running = false;
  var editor;

  // ---------------------------------------------------------------- storage

  function loadState() {
    try {
      return JSON.parse(window.localStorage.getItem(STORAGE_KEY)) || {};
    } catch (err) {
      return {};
    }
  }

  function saveState() {
    try {
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          code: editor ? editor.getValue() : "",
          language: el.language.value,
          mode: el.mode.value,
          workers: el.workers.value,
          theme: document.documentElement.getAttribute("data-theme")
        })
      );
    } catch (err) {
      /* quota exceeded or storage disabled - not worth interrupting the user */
    }
  }

  // ------------------------------------------------------------------ theme

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    el.themeIcon.textContent = theme === "dark" ? "☀" : "☽";
    el.themeToggle.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
    if (editor) {
      editor.setTheme(theme);
    }
  }

  function preferredTheme(stored) {
    if (stored === "dark" || stored === "light") {
      return stored;
    }
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }

  // ----------------------------------------------------------------- output

  function clearOutput() {
    el.output.textContent = "";
    el.output.className = "console";
  }

  function writeConsole(sections, variant) {
    clearOutput();
    if (variant) {
      el.output.classList.add("console--" + variant);
    }
    sections.forEach(function (section) {
      if (!section || !section.text) {
        return;
      }
      if (section.label) {
        var label = document.createElement("span");
        label.className = "console__label";
        label.textContent = section.label;
        el.output.appendChild(label);
      }
      var body = document.createElement("span");
      body.className = section.className || "";
      body.textContent = section.text;
      el.output.appendChild(body);
      el.output.appendChild(document.createTextNode("\n"));
    });
  }

  function setStatus(text, dotClass) {
    el.statusText.textContent = text;
    el.statusDot.className = "dot" + (dotClass ? " dot--" + dotClass : "");
  }

  function flash(button, text) {
    var original = button.textContent;
    button.textContent = text;
    window.setTimeout(function () {
      button.textContent = original;
    }, 1200);
  }

  function copyText(text, button) {
    if (!text) {
      flash(button, "Empty");
      return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(
        function () {
          flash(button, "Copied");
        },
        function () {
          flash(button, "Failed");
        }
      );
    } else {
      flash(button, "Unsupported");
    }
  }

  // --------------------------------------------------------------- examples

  function renderExamples() {
    el.openmpExamples.textContent = "";
    el.mpiExamples.textContent = "";

    examples.forEach(function (example) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "chip";
      button.textContent = example.title;
      button.title = example.description || example.title;
      button.addEventListener("click", function () {
        el.mode.value = example.mode;
        el.language.value = example.language;
        updateWorkerLabel();
        editor.setValue(example.source);
        editor.focus();
        writeConsole(
          [
            {
              text:
                'Loaded "' +
                example.title +
                '" (' +
                example.language.toUpperCase() +
                " / " +
                example.mode.toUpperCase() +
                "). Press Ctrl+Enter to run."
            }
          ],
          null
        );
        saveState();
      });
      (example.mode === "mpi" ? el.mpiExamples : el.openmpExamples).appendChild(button);
    });
  }

  function fetchExamples() {
    return fetch(API_BASE + "/examples")
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .then(function (payload) {
        if (payload && Array.isArray(payload.examples) && payload.examples.length) {
          examples = payload.examples;
          renderExamples();
        }
      })
      .catch(function () {
        /* keep the bundled catalogue */
      });
  }

  // ----------------------------------------------------------------- health

  function describeLimits(limits) {
    if (!limits) {
      return;
    }
    var mb = Math.round((limits.memoryBytes || 0) / (1024 * 1024));
    el.limitsBanner.innerHTML = "";
    var strong = document.createElement("strong");
    strong.textContent = "Note:";
    el.limitsBanner.appendChild(strong);
    el.limitsBanner.appendChild(
      document.createTextNode(
        " code runs in a sandbox limited to " +
          limits.runTimeout +
          "s (" +
          limits.mpiRunTimeout +
          "s for MPI), " +
          mb +
          " MB of memory and " +
          limits.maxWorkers +
          " workers. Do not paste anything sensitive."
      )
    );
  }

  function checkHealth() {
    return fetch(API_BASE + "/health")
      .then(function (response) {
        return response.json();
      })
      .then(function (data) {
        if (data && data.openmp_available) {
          el.backendStatus.textContent = "Online" + (data.mpi_available ? " + MPI" : "");
          if (!running) {
            el.statusDot.className = "dot dot--online";
          }
          describeLimits(data.limits);
          setMpiAvailability(data.mpi_available);
        } else {
          el.backendStatus.textContent = "No compiler";
          el.statusDot.className = "dot dot--offline";
        }
      })
      .catch(function () {
        el.backendStatus.textContent = "Offline";
        el.statusDot.className = "dot dot--offline";
      });
  }

  function setMpiAvailability(available) {
    var mpiOption = el.mode.querySelector('option[value="mpi"]');
    if (!mpiOption) {
      return;
    }
    mpiOption.disabled = !available;
    mpiOption.textContent = available ? "MPI" : "MPI (unavailable)";
  }

  // -------------------------------------------------------------------- run

  function updateWorkerLabel() {
    el.workerLabel.textContent = el.mode.value === "mpi" ? "Procs" : "Threads";
  }

  function setRunning(state) {
    running = state;
    el.runBtn.disabled = state;
    if (state) {
      el.runBtnLabel.textContent = "Running";
      el.runBtn.insertBefore(
        Object.assign(document.createElement("span"), { className: "spinner", id: "runSpinner" }),
        el.runBtn.firstChild
      );
    } else {
      el.runBtnLabel.textContent = "Run";
      var spinner = document.getElementById("runSpinner");
      if (spinner) {
        spinner.remove();
      }
    }
  }

  function formatMeta(result) {
    var parts = [];
    if (result.compiler) {
      parts.push(result.compiler);
    }
    if (typeof result.workers === "number") {
      parts.push(result.workers + (result.mode === "mpi" ? " processes" : " threads"));
    }
    if (result.compileMs) {
      parts.push("compile " + result.compileMs + " ms");
    }
    if (result.runMs) {
      parts.push("run " + result.runMs + " ms");
    }
    if (typeof result.returncode === "number") {
      parts.push("exit " + result.returncode);
    }
    return parts.join("  ·  ");
  }

  function renderResult(result) {
    var failed = result.success === false;
    var sections = [];

    if (result.error) {
      sections.push({ label: result.error, text: result.stderr || "", className: "console__stream--err" });
    } else {
      sections.push({ label: "Output", text: result.output || "(no output)" });
      if (result.stderr) {
        sections.push({ label: "Stderr", text: result.stderr, className: "console__stream--err" });
      }
    }

    if (result.truncated) {
      sections.push({ text: "[output truncated - the program produced more than the limit]" });
    }
    if (result.hint) {
      sections.push({ text: "Hint: " + result.hint, className: "console__hint" });
    }
    var meta = formatMeta(result);
    if (meta) {
      sections.push({ text: meta, className: "console__meta" });
    }

    writeConsole(sections, failed || result.returncode !== 0 ? "error" : "success");
    setStatus(failed ? "Failed" : result.returncode === 0 ? "Completed" : "Exited " + result.returncode,
      failed ? "offline" : "online");
  }

  function runCode() {
    if (running) {
      return;
    }
    var code = editor.getValue();
    if (!code.trim()) {
      writeConsole([{ label: "Nothing to run", text: "Write some code first." }], "error");
      return;
    }

    setRunning(true);
    setStatus("Compiling", "busy");
    writeConsole([{ text: "Compiling…" }], null);
    saveState();

    var controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = window.setTimeout(function () {
      if (controller) {
        controller.abort();
      }
    }, REQUEST_TIMEOUT_MS);

    fetch(API_BASE + "/compile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        code: code,
        language: el.language.value,
        mode: el.mode.value,
        threads: parseInt(el.workers.value, 10)
      }),
      signal: controller ? controller.signal : undefined
    })
      .then(function (response) {
        return response.json().catch(function () {
          throw new Error("The server returned a malformed response (HTTP " + response.status + ").");
        });
      })
      .then(renderResult)
      .catch(function (error) {
        var message =
          error && error.name === "AbortError"
            ? "The request timed out before the server answered."
            : "Could not reach the compiler backend at " + API_BASE + ".\n" + (error.message || error);
        writeConsole([{ label: "Connection error", text: message, className: "console__stream--err" }], "error");
        setStatus("Connection failed", "offline");
      })
      .then(function () {
        window.clearTimeout(timer);
        setRunning(false);
      });
  }

  // ------------------------------------------------------------------- init

  function downloadCode() {
    var name = "program." + (el.language.value === "cpp" ? "cpp" : "c");
    var blob = new Blob([editor.getValue()], { type: "text/plain;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  /**
   * The editor is CodeMirror when the CDN is reachable and a plain textarea
   * when it is not. A dead CDN used to take the whole page down with
   * "CodeMirror is not defined"; now it costs syntax highlighting and nothing
   * else. Both objects expose the same small interface.
   */
  function createEditor(textarea) {
    if (typeof window.CodeMirror === "undefined") {
      return createPlainEditor(textarea);
    }

    var cm = window.CodeMirror.fromTextArea(textarea, {
      mode: "text/x-csrc",
      theme: document.documentElement.getAttribute("data-theme") === "dark" ? "dracula" : "default",
      lineNumbers: true,
      indentUnit: 4,
      tabSize: 4,
      indentWithTabs: false,
      lineWrapping: true,
      matchBrackets: true,
      autoCloseBrackets: true,
      extraKeys: {
        "Ctrl-Enter": runCode,
        "Cmd-Enter": runCode,
        "Ctrl-/": "toggleComment",
        "Cmd-/": "toggleComment"
      }
    });

    return {
      degraded: false,
      getValue: function () {
        return cm.getValue();
      },
      setValue: function (value) {
        cm.setValue(value);
      },
      focus: function () {
        cm.focus();
      },
      setTheme: function (theme) {
        cm.setOption("theme", theme === "dark" ? "dracula" : "default");
      },
      setLanguage: function (language) {
        cm.setOption("mode", language === "cpp" ? "text/x-c++src" : "text/x-csrc");
      },
      onChange: function (handler) {
        cm.on("changes", handler);
      }
    };
  }

  function createPlainEditor(textarea) {
    textarea.classList.add("editor-plain");
    textarea.spellcheck = false;
    textarea.setAttribute("autocomplete", "off");
    textarea.setAttribute("autocapitalize", "off");
    textarea.setAttribute("autocorrect", "off");

    // Tab should indent rather than move focus out of the editor.
    textarea.addEventListener("keydown", function (event) {
      if (event.key !== "Tab") {
        return;
      }
      event.preventDefault();
      var start = textarea.selectionStart;
      var end = textarea.selectionEnd;
      textarea.value = textarea.value.slice(0, start) + "    " + textarea.value.slice(end);
      textarea.selectionStart = textarea.selectionEnd = start + 4;
    });

    return {
      degraded: true,
      getValue: function () {
        return textarea.value;
      },
      setValue: function (value) {
        textarea.value = value;
      },
      focus: function () {
        textarea.focus();
      },
      setTheme: function () {},
      setLanguage: function () {},
      onChange: function (handler) {
        textarea.addEventListener("input", handler);
      }
    };
  }

  function init() {
    var state = loadState();
    applyTheme(preferredTheme(state.theme));

    editor = createEditor(document.getElementById("codeEditor"));

    if (state.language) el.language.value = state.language;
    if (state.mode) el.mode.value = state.mode;
    if (state.workers) el.workers.value = state.workers;
    editor.setValue(
      state.code || (examples.length ? examples[0].source : "int main(void) { return 0; }")
    );

    updateEditorMode();
    updateWorkerLabel();
    renderExamples();
    var ready = [{ text: 'Ready. Press Ctrl+Enter or click "Run" to compile and execute.' }];
    if (editor.degraded) {
      ready.push({
        text:
          "Syntax highlighting is unavailable: the CodeMirror CDN could not be reached. " +
          "Editing, running and every other feature still work.",
        className: "console__hint"
      });
    }
    writeConsole(ready, null);
    setStatus("Ready", null);

    el.runBtn.addEventListener("click", runCode);
    el.clearBtn.addEventListener("click", function () {
      if (editor.getValue().trim() && !window.confirm("Clear the editor?")) {
        return;
      }
      editor.setValue("");
      editor.focus();
      saveState();
    });
    el.clearOutputBtn.addEventListener("click", clearOutput);
    el.copyCodeBtn.addEventListener("click", function () {
      copyText(editor.getValue(), el.copyCodeBtn);
    });
    el.copyOutputBtn.addEventListener("click", function () {
      copyText(el.output.textContent, el.copyOutputBtn);
    });
    el.downloadBtn.addEventListener("click", downloadCode);
    el.themeToggle.addEventListener("click", function () {
      applyTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
      saveState();
    });

    el.mode.addEventListener("change", function () {
      updateWorkerLabel();
      saveState();
    });
    el.language.addEventListener("change", function () {
      updateEditorMode();
      saveState();
    });
    el.workers.addEventListener("change", saveState);
    editor.onChange(debounce(saveState, 800));

    document.addEventListener("keydown", function (event) {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        event.preventDefault();
        runCode();
      }
    });

    fetchExamples();
    checkHealth();
    window.setInterval(checkHealth, HEALTH_INTERVAL_MS);
  }

  function updateEditorMode() {
    editor.setLanguage(el.language.value);
  }

  function debounce(fn, wait) {
    var handle;
    return function () {
      window.clearTimeout(handle);
      handle = window.setTimeout(fn, wait);
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
