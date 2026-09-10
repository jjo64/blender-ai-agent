# 🚀 Arquitectura y Guía Profesional v5.0 (Final Golden Master): Blender AI Agent

Este documento detalla la arquitectura de software definitiva, con todos los bordes pulidos y casos límite resueltos, para construir el **Blender AI Agent**.

---

## 🏗️ 1. Arquitectura del Sistema

```text
blender-ai-agent/
├── __init__.py                # Entry point de la extensión
├── manifest.toml              # Manifiesto para Blender 4.2+ (Extensiones)
│
├── core/                      # Lógica pura (Agnóstica a Blender, testeable)
│   ├── agent.py               # Loop de razonamiento ReAct
│   ├── context_manager.py     # Estrategias de retención (Sliding window + Pinned Decisions)
│   ├── scene_inspector.py     # Schema explícito del contexto de la escena
│   ├── tool_registry.py       # Registro declarativo de herramientas (@tool)
│   ├── security/
│   │   ├── auth_gate.py       # Intercepción de acciones (threading.Event)
│   │   └── sandbox.py         
│   ├── providers/             # Adaptadores estandarizados
│   │   ├── base.py            # Interfaces, Streaming de Texto y Buffering de Herramientas
│   │   └── ... 
│   └── tracker/
│       └── cost_tracker.py    # Uso de tokens reales + prices.json
│
├── blender_integration/       
│   ├── tools/                 
│   ├── state_manager/
│   │   └── checkpoints.py     
│   ├── viewport_capture.py    
│   └── threading_model.py     # Colas tipadas con soporte de Streaming
│
├── state/                     
│   ├── session.py             
│   └── history.py             # Persistencia de supervivencia a crashes
│
├── ui/                        
│   ├── main_panel.py
│   ├── chat_widget.py         
│   └── settings_panel.py
│
├── data/
│   └── prices.json            # Base de datos de costos con metadata de expiración
│
└── docs/                      
    └── ARCHITECTURE.md
```

---

## 🌊 2. UX: Streaming, Texto vs. Tool Calls

El `complete_stream` soporta un modelo de inyección por callbacks (`yield_chunk: callable`) que es ideal para encolar datos hacia la interfaz de Blender sin bloquear. Sin embargo, hay una trampa crítica con el *Function Calling*: las APIs emiten fragmentos JSON rotos e in-parseables durante el streaming.

### Regla del Adapter
El adapter (ej: `openai.py`) debe gestionar esto de manera interna, protegiendo al resto del sistema:
- **Si el stream es texto para el usuario:** Llama a `yield_chunk(StreamChunk(text))` inmediatamente token a token.
- **Si el stream es un argumento de herramienta (JSON):** El adapter acumula silenciosamente el JSON en un buffer interno. Nunca hace yield parcial. Una vez terminado, parsea el objeto y devuelve la estructura completa tipada dentro del objeto `LLMResponse`.

---

## 💾 3. Persistencia de Sesión (History)

Un crash de Blender no debería borrar los últimos 30 minutos de razonamiento del modelo y el usuario.

El `history.py` implementa una **Persistencia de Supervivencia**:
- El historial se guarda tras cada mensaje en un archivo JSON en la carpeta temporal de Blender (`bpy.app.tempdir`).
- **Nomenclatura:** Toma el nombre del archivo de Blender en uso (ej. `mech_robot_v2_agent_history.json`). 
- **Beneficio:** Sobrevive cierres de sesión de Blender (ya que el OS y Blender retienen los temporales por un tiempo prudencial), pero no "ensucia" la carpeta del proyecto del usuario a largo plazo.

---

## 💰 4. Mecanismo de Actualización de Costos

Para evitar que el `cost_tracker` se vuelva inútil a los 3 meses cuando los proveedores cambien sus precios de API, empleamos un sistema de **Alerta de Caducidad** en lugar de auto-fetching (para mantener el Add-on estrictamente offline si el usuario lo prefiere y reducir mantenimiento).

```json
// data/prices.json
{
  "last_updated": "2026-08-01",
  "models": {
    "claude-sonnet-4-6": { "input": 3.0, "output": 15.0 },
    "gemini-3.5-pro": { "input": 1.25, "output": 5.0 }
  }
}
```
**Lógica UI:** Al cargar el Add-on, si detecta que han pasado más de 60 días desde `last_updated`, muestra una pequeña alerta en el panel de UI: *"Los precios de API pueden estar desactualizados. Revisa GitHub para descargar el último prices.json."*

---

## 🚦 5. Recapitulando Acuerdos Clave (Resumen)

1. **Tool Registry:** `@tool` decorators. Cero "God Objects".
2. **Concurrencia (Worker ↔ UI):** `queue.Queue` y `bpy.app.timers`. 
3. **Auth Gate:** `threading.Event` bloquea al Worker de forma segura esperando el "click" de aprobación de la UI.
4. **Scene Inspector:** Dataclass restringida. Prohibido mandar arrays de vértices completos; solo enviar estado semántico (Cuentas, selección actual, object stats).
5. **Pinned Decisions:** El Historial protege resúmenes técnicos para que el VLM no "olvide" decisiones importantes.
6. **Iteraciones Configurables:** `MAX_ITERATIONS` es un setting (ej: 10), con alertas pre-corte en la UI.
