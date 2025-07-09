# 🖐️ Hands Free TRAQ

**Hands Free TRAQ** is a voice-first Android application that guides users through the process of completing the ISA TRAQ (Tree Risk Assessment Qualification) form entirely hands-free. Built using Jetpack Compose and Kotlin for the front-end and Python for backend logic via Chaquopy, the app supports fully offline operation using an onboard speech-to-text engine and local LLM, or optionally integrates OpenAI as a backend. It enables verbal data entry, corrections, and AI-assisted form review, then exports a completed PDF and related images into a structured directory system for archival and reporting.

---

## 📦 Project Structure

### 🧱 Architecture Overview

#### 🔹 UI Layer: **Jetpack Compose (Kotlin)**

- Section-by-section voice-driven form interface
- Displays current prompt, interim text, and progress
- Text-to-speech feedback for each question and review
- Review mode with verbal confirmation for each response

#### 🔹 Logic Layer: **Python via Chaquopy**

- Uses **Pydantic** models to represent the full TRAQ form
- Maintains in-memory form state
- Handles verbal corrections by field reference
- Generates structured **PDF reports**
- Manages image and file exports
- Supports swappable **LLM backend** (local or cloud)

---

### 🧠 LLM Integration

| Mode | Description |
|------|-------------|
| **Local** | On-device LLM (e.g., Mistral, TinyLLM) via `llama-cpp-python` |
| **Remote** | OpenAI GPT-3.5/4 API |
| **Switching** | Configurable backend via shared `LLMClient` interface |

LLM is used to:
- Interpret corrections and spoken input
- Normalize free-form responses
- Generate review-time prompts

---

### 📂 File Output Structure

| Path | Description |
|------|-------------|
| `/created/clientid-date/` | Output folder for a new report |
| `/created/clientid-date/form.json` | Serialized form model (Pydantic) |
| `/created/clientid-date/report.pdf` | Generated PDF report |
| `/created/clientid-date/images/` | Imported or associated images |
| `/created/clientid-date/log.txt` | Voice input and correction logs |
| `/reviewed/clientid-date/` | Final version after review |
| `/reviewed/clientid-date/report.pdf` | Final reviewed PDF |
| `/reviewed/clientid-date/images/` | Final image set |
| `/reviewed/clientid-date/log.txt` | Final review log file |

---

### 🗣️ Voice & Audio System

| Function | Technology |
|----------|------------|
| **Speech-to-Text** | On-device Whisper model (via JNI or subprocess) |
| **Text-to-Speech** | Android TTS engine |
| **Voice Flow Control** | Mic capture and result handling in Kotlin |
| **LLM Command Parsing** | Interprets user intent (e.g., correction, navigation) |

---

### 🧰 Tech Stack Summary

| Layer | Technology |
|-------|------------|
| UI | Kotlin + Jetpack Compose |
| Business Logic | Python (via Chaquopy) |
| Form Modeling | Pydantic |
| PDF Generation | ReportLab / FPDF |
| LLM Integration | `llama-cpp-python` or OpenAI API |
| STT | Whisper (on-device) |
| TTS | Android Text-to-Speech |
| Packaging | Gradle + Chaquopy plugin |
| File Storage | Android file APIs, Python I/O |
