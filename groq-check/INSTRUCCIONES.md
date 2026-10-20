# Prueba acotada de Groq: texto e imágenes

El usuario pidió comprobar si su API Groq actual puede servir como respaldo del agente editorial. No implementar ni activar todavía el fallback; no tocar timers, producción, credenciales sociales ni B-59.

La copia de nube no tiene GROQ_API_KEY, .env ni .env.txt. La configuración administrada tampoco tiene un binding Groq y api.groq.com no está permitido en esa nube. La prueba local de presencia terminó missing_key; no se hicieron llamadas reales a Groq.

El repo contiene ai/groq_client.py y GroqAiClient, con candidatos Llama 4 Scout/Maverick y otros modelos de texto. Su presencia en el código no confirma su disponibilidad actual. El cliente está orientado a texto, no tiene un método dedicado de revisión visual y elimina HTTP_PROXY/HTTPS_PROXY al inicializar: no instanciarlo para esta prueba ni copiar ese comportamiento a la nube.

Ejecutar check_groq.py desde la PC donde esté la clave real, usando el venv del checkout efectivo. No asumir C: si el proyecto activo está en G:. El script carga GROQ_API_KEY del proceso, luego .env y .env.txt sin sobreescribir. No imprime ni guarda la clave. No pasarla por argumentos. Guardar script e informe fuera del repositorio.

Ejemplo PowerShell, adaptando la ubicación de ambos archivos:

    & .\.venv\Scripts\python.exe "$env:LOCALAPPDATA\VideoOptimizer\groq-check\check_groq.py" --repo . --out "$env:LOCALAPPDATA\VideoOptimizer\groq-check\resultado.json"

Hace como máximo cuatro solicitudes: catálogo, una prueba textual y hasta dos candidatos con visión reconocidos por nombre. Usa una imagen sintética generada en memoria con un código aleatorio y figuras; no envía videos, imágenes del canal, credenciales sociales ni documentos privados. Hay un límite pequeño de salida por prueba; puede consumir cuota de la cuenta de Groq. No prueba todos los modelos ni verifica precios/contrato.

La detección de candidatos por nombre es una heurística: si no encuentra uno o todos fallan, no concluir automáticamente que toda la cuenta carece de visión. Consultar el catálogo/documentación oficial vigente antes de ampliar la prueba. Registrar los HTTP status; no imprimir respuestas de error crudas que puedan contener datos confidenciales. No desactivar TLS ni proxies ni intentar sortear restricciones.

Entregar un informe sin secretos con autenticación, modelo textual, modelos visuales probados, lectura de código/figuras, detección del recorte, tokens/latencia y limitaciones. Un pase de esta imagen confirma visión básica; no demuestra calidad editorial, investigación web, verificación histórica, revisión de licencias ni sustitución completa de Codex. Esos pasos requieren una evaluación posterior con muestras conocidas y un adaptador de herramientas.

El script se comprobó en nube únicamente en la rama de clave ausente. Las llamadas reales quedan pendientes de la PC. No afirmar validación de cuenta antes de ejecutarlas.
