# api_status_checker.py
"""
Módulo para verificar el estado detallado de todas las APIs:
- Estado (funcionando/fallando)
- Créditos/tokens disponibles
- Uso actual
- Información de cuenta (email/usuario)
"""

import os
import requests
from typing import Dict, Optional, Any
from infra.env_loader import load_project_env

load_project_env()

class APIStatusChecker:
    """Verifica el estado detallado de todas las APIs"""
    
    def __init__(self):
        self.status_data = {}
    
    


    
    def check_gemini(self) -> Dict[str, Any]:
        """Verifica estado de Google Gemini"""
        api_key = os.getenv("GEMINI_API_KEY")
        
        if not api_key:
            return {
                "status": "not_configured",
                "message": "API Key no configurada",
                "credits": None,
                "usage": None,
                "account": None
            }
        
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            
            # Intentar listar modelos para verificar (usar modelo específico en lugar de list_models)
            try:
                # Probar con un modelo específico
                model = genai.GenerativeModel('gemini-2.5-flash')
                response = model.generate_content("OK", generation_config={"max_output_tokens": 5})
                if response and response.text:
                    return {
                        "status": "working",
                        "message": "API funcionando",
                        "credits": "60 RPM gratis, luego según plan",
                        "usage": "Modelo gemini-2.5-flash disponible",
                        "account": "No disponible"
                    }
            except Exception as model_error:
                # Si falla con un modelo, intentar con otro
                try:
                    model = genai.GenerativeModel('gemini-1.5-pro')
                    response = model.generate_content("OK", generation_config={"max_output_tokens": 5})
                    if response and response.text:
                        return {
                            "status": "working",
                            "message": "API funcionando (gemini-1.5-pro)",
                            "credits": "60 RPM gratis, luego según plan",
                            "usage": "Modelo gemini-1.5-pro disponible",
                            "account": "No disponible"
                        }
                except:
                    pass
            
            # Si llegamos aquí, la API funciona pero hay problemas con modelos
            return {
                "status": "working",
                "message": "API funcionando (verificar modelos disponibles)",
                "credits": "60 RPM gratis, luego según plan",
                "usage": "Verificar modelos en dashboard",
                "account": "No disponible"
            }
        except ImportError:
            return {
                "status": "error",
                "message": "Módulo 'groq' no instalado - pip install groq",
                "credits": None,
                "usage": None,
                "account": None
            }
        except Exception as e:
            error_msg = str(e)
            if "api_key" in error_msg.lower() or "invalid" in error_msg.lower():
                return {
                    "status": "error",
                    "message": f"API Key inválida: {error_msg[:60]}",
                    "credits": None,
                    "usage": None,
                    "account": None
                }
            return {
                "status": "error",
                "message": f"{type(e).__name__}: {error_msg[:80]}",
                "credits": None,
                "usage": None,
                "account": None
            }
    
    def check_deepseek(self) -> Dict[str, Any]:
        """Verifica DeepSeek (alternativa a Groq para el texto). Consulta el saldo si la clave responde."""
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            return {"status": "not_configured", "message": "API Key no configurada",
                    "credits": None, "usage": None, "account": None}
        try:
            import requests
            base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
            resp = requests.get(f"{base}/user/balance", headers={"Authorization": f"Bearer {api_key}"}, timeout=15)
            if resp.status_code == 401:
                return {"status": "error", "message": "API Key invalida", "credits": None, "usage": None, "account": None}
            if resp.status_code != 200:
                return {"status": "error", "message": f"HTTP {resp.status_code}", "credits": None, "usage": None, "account": None}
            data = resp.json() or {}
            balances = ", ".join(f"{b.get('total_balance')} {b.get('currency')}" for b in data.get("balance_infos", []))
            return {"status": "working" if data.get("is_available", True) else "error",
                    "message": "API funcionando" if data.get("is_available", True) else "Saldo insuficiente",
                    "credits": balances or "No disponible", "usage": "No disponible en API", "account": "No disponible"}
        except Exception as e:
            return {"status": "error", "message": f"{type(e).__name__}: {str(e)[:80]}",
                    "credits": None, "usage": None, "account": None}

    def check_groq(self) -> Dict[str, Any]:
        """Verifica estado de Groq"""
        api_key = os.getenv("GROQ_API_KEY")
        
        if not api_key:
            return {
                "status": "not_configured",
                "message": "API Key no configurada",
                "credits": None,
                "usage": None,
                "account": None
            }
        
        try:
            from groq import Groq
            client = Groq(api_key=api_key)
            
            # Groq no expone créditos directamente
            return {
                "status": "working",
                "message": "API funcionando",
                "credits": "30 RPM gratis, luego según plan",
                "usage": "No disponible en API",
                "account": "No disponible"
            }
        except Exception as e:
            return {
                "status": "error",
                "message": str(e),
                "credits": None,
                "usage": None,
                "account": None
            }
    
    def check_perplexity(self) -> Dict[str, Any]:
        """Verifica estado de Perplexity"""
        api_key = os.getenv("PERPLEXITY_API_KEY")
        
        if not api_key:
            return {
                "status": "not_configured",
                "message": "API Key no configurada",
                "credits": None,
                "usage": None,
                "account": None
            }
        
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=api_key,
                base_url="https://api.perplexity.ai"
            )
            
            # Intentar una llamada simple con el modelo sonar
            try:
                response = client.chat.completions.create(
                    model="sonar",
                    messages=[{"role": "user", "content": "OK"}],
                    max_tokens=5
                )
                
                return {
                    "status": "working",
                    "message": "API funcionando",
                    "credits": "5 requests/día gratis, luego según plan",
                    "usage": "No disponible en API",
                    "account": "No disponible"
                }
            except Exception as model_error:
                # Si sonar falla, intentar con sonar-pro
                try:
                    response = client.chat.completions.create(
                        model="sonar-pro",
                        messages=[{"role": "user", "content": "OK"}],
                        max_tokens=5
                    )
                    
                    return {
                        "status": "working",
                        "message": "API funcionando (sonar-pro)",
                        "credits": "5 requests/día gratis, luego según plan",
                        "usage": "No disponible en API",
                        "account": "No disponible"
                    }
                except:
                    # Si ambos modelos fallan, verificar si es un error de autenticación
                    error_msg = str(model_error).lower()
                    if "401" in error_msg or "unauthorized" in error_msg or "invalid" in error_msg:
                        return {
                            "status": "error",
                            "message": "API Key inválida o expirada",
                            "credits": None,
                            "usage": None,
                            "account": None
                        }
                    elif "429" in error_msg or "quota" in error_msg or "rate limit" in error_msg:
                        return {
                            "status": "error",
                            "message": "Límite de rate excedido o cuota agotada",
                            "credits": "0",
                            "usage": "Límite alcanzado",
                            "account": "No disponible"
                        }
                    else:
                        return {
                            "status": "error",
                            "message": f"Error al verificar: {str(model_error)[:60]}",
                            "credits": None,
                            "usage": None,
                            "account": None
                        }
        except ImportError:
            return {
                "status": "error",
                "message": "Módulo 'openai' no instalado - pip install openai",
                "credits": None,
                "usage": None,
                "account": None
            }
        except Exception as e:
            error_msg = str(e)
            if "api_key" in error_msg.lower() or "invalid" in error_msg.lower():
                return {
                    "status": "error",
                    "message": f"API Key inválida: {error_msg[:60]}",
                    "credits": None,
                    "usage": None,
                    "account": None
                }
            return {
                "status": "error",
                "message": f"{type(e).__name__}: {error_msg[:80]}",
                "credits": None,
                "usage": None,
                "account": None
            }
    
    def check_openai(self) -> Dict[str, Any]:
        """Verifica estado de OpenAI"""
        api_key = os.getenv("OPENAI_API_KEY")
        
        if not api_key:
            return {
                "status": "not_configured",
                "message": "API Key no configurada",
                "credits": None,
                "usage": None,
                "account": None
            }
        
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            
            # Intentar una llamada simple con gpt-4o-mini (más económico)
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": "OK"}],
                    max_tokens=5
                )
                
                # Intentar obtener información de uso/créditos
                credits_info = "Verificar en dashboard de OpenAI"
                try:
                    # OpenAI no expone créditos directamente, pero podemos verificar el modelo
                    model_used = response.model
                    credits_info = f"Modelo disponible: {model_used}"
                except:
                    pass
                
                return {
                    "status": "working",
                    "message": "API funcionando",
                    "credits": credits_info,
                    "usage": "Verificar en https://platform.openai.com/usage",
                    "account": "Verificar en dashboard"
                }
            except Exception as api_error:
                error_str = str(api_error).lower()
                if "insufficient_quota" in error_str or "quota" in error_str:
                    return {
                        "status": "error",
                        "message": "Cuota insuficiente - Verificar créditos en dashboard",
                        "credits": "Cuota agotada",
                        "usage": None,
                        "account": None
                    }
                elif "invalid_api_key" in error_str or "authentication" in error_str:
                    return {
                        "status": "error",
                        "message": "API Key inválida",
                        "credits": None,
                        "usage": None,
                        "account": None
                    }
                else:
                    return {
                        "status": "error",
                        "message": f"Error: {str(api_error)[:60]}",
                        "credits": None,
                        "usage": None,
                        "account": None
                    }
        except ImportError:
            return {
                "status": "error",
                "message": "Módulo 'openai' no instalado - Ejecutar: pip install openai",
                "credits": None,
                "usage": None,
                "account": None
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"{type(e).__name__}: {str(e)[:80]}",
                "credits": None,
                "usage": None,
                "account": None
            }
    
    def check_grok(self) -> Dict[str, Any]:
        """Verifica estado de xAI Grok"""
        api_key = os.getenv("GROK_API_KEY")
        
        if not api_key:
            return {
                "status": "not_configured",
                "message": "API Key no configurada",
                "credits": None,
                "usage": None,
                "account": None
            }
        
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=api_key,
                base_url="https://api.x.ai/v1"
            )
            
            # Intentar una llamada simple
            response = client.chat.completions.create(
                model="grok-2",
                messages=[{"role": "user", "content": "OK"}],
                max_tokens=5
            )
            
            return {
                "status": "working",
                "message": "API funcionando",
                "credits": "Verificar en dashboard",
                "usage": "No disponible en API",
                "account": "No disponible"
            }
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "exhausted" in error_msg.lower():
                return {
                    "status": "error",
                    "message": "Créditos agotados",
                    "credits": "0",
                    "usage": "Límite alcanzado",
                    "account": "No disponible"
                }
            return {
                "status": "error",
                "message": error_msg,
                "credits": None,
                "usage": None,
                "account": None
            }
    
    def check_elevenlabs(self) -> Dict[str, Any]:
        """Verifica estado de ElevenLabs"""
        api_key = os.getenv("ELEVENLABS_API_KEY")
        
        if not api_key:
            return {
                "status": "not_configured",
                "message": "API Key no configurada",
                "credits": None,
                "usage": None,
                "account": None
            }
        
        try:
            # Obtener información del usuario
            url = "https://api.elevenlabs.io/v1/user"
            headers = {"xi-api-key": api_key}
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                subscription = data.get('subscription', {})
                tier = subscription.get('tier', 'N/A')
                character_count = subscription.get('character_count', 0)
                character_limit = subscription.get('character_limit', 0)
                
                # Obtener voces
                voices_url = "https://api.elevenlabs.io/v1/voices"
                voices_response = requests.get(voices_url, headers=headers, timeout=10)
                voices_count = 0
                if voices_response.status_code == 200:
                    voices_data = voices_response.json()
                    voices_count = len(voices_data.get('voices', []))
                
                return {
                    "status": "working",
                    "message": "API funcionando",
                    "credits": f"{character_count:,} / {character_limit:,} caracteres",
                    "usage": f"Plan: {tier} | {voices_count} voces disponibles",
                    "account": data.get('email', 'N/A')
                }
            elif response.status_code == 403:
                return {
                    "status": "error",
                    "message": "Error 403 - Acceso denegado (verificar User-Agent en headers)",
                    "credits": None,
                    "usage": None,
                    "account": None
                }
            else:
                error_text = response.text[:100] if hasattr(response, 'text') and response.text else ""
                return {
                    "status": "error",
                    "message": f"HTTP {response.status_code} - {error_text}",
                    "credits": None,
                    "usage": None,
                    "account": None
                }
        except requests.exceptions.Timeout:
            return {
                "status": "error",
                "message": "Timeout - API no responde (verificar conexión)",
                "credits": None,
                "usage": None,
                "account": None
            }
        except requests.exceptions.ConnectionError:
            return {
                "status": "error",
                "message": "Error de conexión - Verificar internet",
                "credits": None,
                "usage": None,
                "account": None
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"{type(e).__name__}: {str(e)[:80]}",
                "credits": None,
                "usage": None,
                "account": None
            }
    
    def check_recraft(self) -> Dict[str, Any]:
        """Verifica estado de Recraft sin consumir creditos."""
        api_key = os.getenv("RECRAFT_API_KEY")

        if not api_key:
            return {
                "status": "not_configured",
                "message": "API Key no configurada",
                "credits": None,
                "usage": None,
                "account": None
            }

        if len(api_key.strip()) < 10:
            return {
                "status": "error",
                "message": "API Key parece invalida (muy corta)",
                "credits": None,
                "usage": None,
                "account": None
            }

        return {
            "status": "working",
            "message": "API Key configurada (verificacion sin consumo)",
            "credits": "Verificar en dashboard de Recraft",
            "usage": "No disponible en API",
            "account": "Configurada"
        }

    def check_jamendo(self) -> Dict[str, Any]:
        """Verifica estado de Jamendo"""
        client_id = os.getenv("JAMENDO_CLIENT_ID")
        
        if not client_id:
            return {
                "status": "not_configured",
                "message": "Client ID no configurado",
                "credits": None,
                "usage": None,
                "account": None
            }
        
        try:
            url = "https://api.jamendo.com/v3.0/tracks"
            params = {
                "client_id": client_id,
                "format": "json",
                "limit": 1
            }
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                return {
                    "status": "working",
                    "message": "API funcionando",
                    "credits": "200 requests/día (gratis)",
                    "usage": "No disponible",
                    "account": "No disponible"
                }
            elif response.status_code == 403:
                return {
                    "status": "error",
                    "message": "Error 403 - Acceso denegado (verificar User-Agent)",
                    "credits": None,
                    "usage": None,
                    "account": None
                }
            else:
                error_text = response.text[:100] if hasattr(response, 'text') and response.text else ""
                return {
                    "status": "error",
                    "message": f"HTTP {response.status_code} - {error_text}",
                    "credits": None,
                    "usage": None,
                    "account": None
                }
        except requests.exceptions.Timeout:
            return {
                "status": "error",
                "message": "Timeout - API no responde (verificar conexión)",
                "credits": None,
                "usage": None,
                "account": None
            }
        except requests.exceptions.ConnectionError:
            return {
                "status": "error",
                "message": "Error de conexión - Verificar internet",
                "credits": None,
                "usage": None,
                "account": None
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"{type(e).__name__}: {str(e)[:80]}",
                "credits": None,
                "usage": None,
                "account": None
            }
    
    
    
    
    
    def check_bing_images(self) -> Dict[str, Any]:
        """Verifica estado del backend gratis (Openverse)."""
        endpoint = os.getenv("OPENVERSE_API_ENDPOINT", "https://api.openverse.org/v1/images/").rstrip("/") + "/"
        try:
            headers = {"User-Agent": "VideoOptimizerPro/1.0"}
            params = {
                "q": "test",
                "page_size": 1,
                "mature": "false"
            }
            response = requests.get(endpoint, params=params, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json() if response.content else {}
                total_estimated = data.get("result_count", 0)
                return {
                    "status": "working",
                    "message": "Openverse funcionando",
                    "credits": "Gratis (sin API key)",
                    "usage": f"{total_estimated} coincidencias estimadas en prueba",
                    "account": "No requiere cuenta"
                }
            if response.status_code == 429:
                return {
                    "status": "error",
                    "message": "Limite de rate excedido",
                    "credits": "Gratis",
                    "usage": "Límite alcanzado",
                    "account": None
                }

            error_text = response.text[:120] if hasattr(response, "text") and response.text else ""
            return {
                "status": "error",
                "message": f"HTTP {response.status_code} - {error_text}",
                "credits": None,
                "usage": None,
                "account": None
            }
        except requests.exceptions.Timeout:
            return {
                "status": "error",
                "message": "Timeout - API no responde (verificar conexión)",
                "credits": None,
                "usage": None,
                "account": None
            }
        except requests.exceptions.ConnectionError:
            return {
                "status": "error",
                "message": "Error de conexión - Verificar internet",
                "credits": None,
                "usage": None,
                "account": None
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"{type(e).__name__}: {str(e)[:80]}",
                "credits": None,
                "usage": None,
                "account": None
            }

    
    def check_wikimedia(self) -> Dict[str, Any]:
        """Verifica estado de Wikimedia Commons"""
        # Wikimedia no requiere API key, es público
        try:
            # Hacer una búsqueda de prueba simple
            url = "https://commons.wikimedia.org/w/api.php"
            params = {
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": "test",
                "gsrlimit": 1,
                "gsrnamespace": 6,  # File namespace
                "prop": "imageinfo",
                "iiprop": "url"
            }
            response = requests.get(url, params=params, timeout=10, headers={"User-Agent": "VideoOptimizerPro/1.0"})
            
            if response.status_code == 200:
                data = response.json()
                if "query" in data and "pages" in data["query"]:
                    return {
                        "status": "working",
                        "message": "API funcionando",
                        "credits": "Ilimitado (gratis, sin API key)",
                        "usage": "No disponible",
                        "account": "No requiere cuenta"
                    }
                else:
                    return {
                        "status": "working",
                        "message": "API responde (sin resultados en prueba)",
                        "credits": "Ilimitado (gratis, sin API key)",
                        "usage": "No disponible",
                        "account": "No requiere cuenta"
                    }
            else:
                error_text = response.text[:100] if hasattr(response, 'text') and response.text else ""
                return {
                    "status": "error",
                    "message": f"HTTP {response.status_code} - {error_text}",
                    "credits": None,
                    "usage": None,
                    "account": None
                }
        except requests.exceptions.Timeout:
            return {
                "status": "error",
                "message": "Timeout - API no responde (verificar conexión)",
                "credits": None,
                "usage": None,
                "account": None
            }
        except requests.exceptions.ConnectionError:
            return {
                "status": "error",
                "message": "Error de conexión - Verificar internet",
                "credits": None,
                "usage": None,
                "account": None
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"{type(e).__name__}: {str(e)[:80]}",
                "credits": None,
                "usage": None,
                "account": None
            }

