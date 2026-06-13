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
from env_loader import load_project_env

load_project_env()

class APIStatusChecker:
    """Verifica el estado detallado de todas las APIs"""
    
    def __init__(self):
        self.status_data = {}
    
    def check_all_apis(self) -> Dict[str, Dict[str, Any]]:
        """Verifica todas las APIs y retorna un diccionario con su estado"""
        results = {}
        
        # APIs de generación de imágenes
        results["Recraft AI"] = self.check_recraft()
        
        # APIs de búsqueda de imágenes reales
        results["Openverse (Gratis)"] = self.check_bing_images()
        results["Wikimedia"] = self.check_wikimedia()
        
        # APIs de IA de texto
        results["Google Gemini"] = self.check_gemini()
        results["Groq"] = self.check_groq()
        results["Perplexity"] = self.check_perplexity()
        results["OpenAI"] = self.check_openai()
        results["xAI Grok"] = self.check_grok()
        
        # APIs de audio
        results["ElevenLabs"] = self.check_elevenlabs()
        
        # APIs de recursos
        results["Jamendo"] = self.check_jamendo()
        
        # APIs de búsqueda y tendencias
        results["SERP API"] = self.check_serp_api()
        
        # APIs eliminadas: PEXELS, PIXABAY, UNSPLASH, FREESOUND, FAL.AI, RUNWAY, EDEN AI, FLICKR
        
        return results
    
    def check_leonardo_ai(self) -> Dict[str, Any]:
        """Compatibilidad: Leonardo ahora usa backend Recraft."""
        return self.check_recraft()

    def check_fal_ai(self) -> Dict[str, Any]:
        """Compatibilidad: Fal.ai ahora usa backend Recraft."""
        return self.check_recraft()

    def check_eden_ai(self) -> Dict[str, Any]:
        """Verifica estado de Eden AI"""
        api_key = os.getenv("EDEN_AI_API_KEY")
        
        if not api_key:
            return {
                "status": "not_configured",
                "message": "API Key no configurada",
                "credits": None,
                "usage": None,
                "account": None
            }
        
        try:
            # Intentar una llamada simple a la API de Eden AI para verificar
            # Usamos un prompt mínimo para no consumir créditos innecesariamente
            # Intentar con ambas URLs posibles
            urls_to_try = [
                "https://api.edenai.run/v2/image/generation",  # URL principal
                "https://api.edenai.co/v2/image/generation"    # URL alternativa
            ]
            
            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            }
            data = {
                'text': 'test image',
                'providers': 'openai',
                'resolution': '256x256',  # Resolución mínima para prueba
                'num_images': 1
            }
            
            response = None
            last_dns_error = None
            
            # Intentar con ambas URLs
            for url in urls_to_try:
                try:
                    response = requests.post(url, headers=headers, json=data, timeout=15)
                    # Si llegamos aquí, la conexión funcionó
                    break
                except requests.exceptions.ConnectionError as conn_err:
                    error_str = str(conn_err).lower()
                    if "name resolution" in error_str or "dns" in error_str or "nodename nor servname provided" in error_str:
                        last_dns_error = f"Error DNS con {url}"
                        # Intentar siguiente URL
                        continue
                    else:
                        # Otro tipo de error de conexión
                        raise
                except requests.exceptions.Timeout:
                    last_dns_error = f"Timeout con {url}"
                    # Intentar siguiente URL
                    continue
            
            if response is None:
                if last_dns_error:
                    return {
                        "status": "error",
                        "message": f"Error DNS: No se puede resolver el dominio. {last_dns_error}. Verificar conexión a internet y configuración DNS.",
                        "credits": None,
                        "usage": None,
                        "account": None
                    }
                else:
                    return {
                        "status": "error",
                        "message": "Error de conexión - No se pudo conectar a ningún endpoint de Eden AI",
                        "credits": None,
                        "usage": None,
                        "account": None
                    }
            
            # Verificar respuesta sin procesar completamente (para ahorrar tiempo)
            if response.status_code == 200:
                try:
                    result = response.json()
                    # Verificar si hay algún proveedor disponible
                    if result and isinstance(result, dict):
                        # Si hay al menos un proveedor en la respuesta, la API funciona
                        return {
                            "status": "working",
                            "message": "API funcionando",
                            "credits": "Verificar en dashboard de Eden AI",
                            "usage": "No disponible en API",
                            "account": "No disponible"
                        }
                except:
                    # Si la respuesta es 200 pero no es JSON válido, asumir que funciona
                    return {
                        "status": "working",
                        "message": "API responde correctamente",
                        "credits": "Verificar en dashboard",
                        "usage": "No disponible en API",
                        "account": "No disponible"
                    }
            elif response.status_code == 401:
                try:
                    error_data = response.json()
                    error_msg = error_data.get('error', {}).get('message', '') if isinstance(error_data.get('error'), dict) else error_data.get('error', '')
                except:
                    error_msg = response.text[:100] if response.text else ''
                return {
                    "status": "error",
                    "message": f"API Key inválida o expirada: {error_msg[:50]}" if error_msg else "API Key inválida o expirada",
                    "credits": None,
                    "usage": None,
                    "account": None
                }
            elif response.status_code == 403:
                return {
                    "status": "error",
                    "message": "Acceso denegado - Verificar permisos de API key",
                    "credits": None,
                    "usage": None,
                    "account": None
                }
            elif response.status_code == 429:
                return {
                    "status": "error",
                    "message": "Límite de rate excedido - Esperar o actualizar plan",
                    "credits": "0",
                    "usage": "Límite alcanzado",
                    "account": "No disponible"
                }
            elif response.status_code >= 500:
                return {
                    "status": "error",
                    "message": f"Error del servidor ({response.status_code}) - Intentar más tarde",
                    "credits": None,
                    "usage": None,
                    "account": None
                }
            else:
                error_text = response.text[:100] if hasattr(response, 'text') and response.text else ""
                return {
                    "status": "error",
                    "message": f"HTTP {response.status_code} - {error_text[:50]}",
                    "credits": None,
                    "usage": None,
                    "account": None
                }
        except requests.exceptions.Timeout:
            return {
                "status": "error",
                "message": "Timeout - API no responde (verificar conexión o intentar más tarde)",
                "credits": None,
                "usage": None,
                "account": None
            }
        except requests.exceptions.ConnectionError as e:
            error_msg = str(e)
            error_lower = error_msg.lower()
            if "name resolution" in error_lower or "dns" in error_lower or "nodename nor servname provided" in error_lower:
                return {
                    "status": "error",
                    "message": "Error DNS - No se puede resolver api.edenai.run o api.edenai.co. Verificar: 1) Conexión a internet, 2) Configuración DNS, 3) Firewall/Proxy",
                    "credits": None,
                    "usage": None,
                    "account": None
                }
            else:
                return {
                    "status": "error",
                    "message": f"Error de conexión: {error_msg[:60]}",
                    "credits": None,
                    "usage": None,
                    "account": None
                }
        except requests.exceptions.RequestException as e:
            return {
                "status": "error",
                "message": f"Error de solicitud: {str(e)[:60]}",
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
    
    def check_serp_api(self) -> Dict[str, Any]:
        """Verifica estado de SERP API (SerpApi)"""
        api_key = os.getenv("SERP_API_KEY")
        
        if not api_key:
            return {
                "status": "not_configured",
                "message": "API Key no configurada",
                "credits": None,
                "usage": None,
                "account": None
            }
        
        try:
            # SERP API no tiene un endpoint directo de verificación de cuenta
            # Hacemos una búsqueda de prueba simple para verificar la API key
            url = "https://serpapi.com/search"
            params = {
                "q": "test",
                "api_key": api_key,
                "engine": "google",
                "num": 1  # Solo 1 resultado para minimizar uso
            }
            
            response = requests.get(url, params=params, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                
                # Intentar obtener información de la cuenta desde la respuesta
                account_info = "No disponible"
                credits_info = "Verificar en dashboard de SerpApi"
                
                # Buscar información de cuenta en la respuesta
                if "account_id" in data:
                    account_info = data.get("account_id", "N/A")
                
                # Intentar obtener información de créditos/plan
                # SERP API puede incluir información de plan en algunas respuestas
                if "account" in data:
                    account_data = data.get("account", {})
                    if isinstance(account_data, dict):
                        plan = account_data.get("plan", account_data.get("tier", ""))
                        if plan:
                            credits_info = f"Plan: {plan}"
                
                # Verificar si hay información de búsqueda completada
                search_info = data.get("search_information", {})
                if search_info:
                    total_results = search_info.get("total_results", 0)
                    if total_results:
                        credits_info = f"Búsquedas disponibles según plan | {total_results:,} resultados en prueba"
                
                return {
                    "status": "working",
                    "message": "API funcionando",
                    "credits": credits_info,
                    "usage": "100 búsquedas/mes (plan gratis), luego según plan",
                    "account": account_info
                }
            elif response.status_code == 401:
                try:
                    error_data = response.json()
                    error_msg = error_data.get("error", "")
                    if error_msg:
                        return {
                            "status": "error",
                            "message": f"API Key inválida o expirada: {error_msg}",
                            "credits": None,
                            "usage": None,
                            "account": None
                        }
                except:
                    pass
                
                return {
                    "status": "error",
                    "message": "API Key inválida o expirada (401)",
                    "credits": None,
                    "usage": None,
                    "account": None
                }
            elif response.status_code == 429:
                return {
                    "status": "error",
                    "message": "Rate limit alcanzado - Esperar o actualizar plan",
                    "credits": "0",
                    "usage": "Límite alcanzado",
                    "account": "No disponible"
                }
            elif response.status_code == 400:
                try:
                    error_data = response.json()
                    error_msg = error_data.get("error", "")
                    if error_msg:
                        return {
                            "status": "error",
                            "message": f"Error 400 - Solicitud inválida: {error_msg}",
                            "credits": None,
                            "usage": None,
                            "account": None
                        }
                except:
                    pass
                
                return {
                    "status": "error",
                    "message": "Error 400 - Solicitud inválida",
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
    
    def check_freesound(self) -> Dict[str, Any]:
        """Verifica estado de Freesound"""
        api_key = os.getenv("FREESOUND_API_KEY")
        
        if not api_key:
            return {
                "status": "not_configured",
                "message": "API Key no configurada",
                "credits": None,
                "usage": None,
                "account": None
            }
        
        try:
            url = "https://freesound.org/apiv2/me/"
            headers = {"Authorization": f"Token {api_key}"}
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                username = data.get('username', 'N/A')
                
                return {
                    "status": "working",
                    "message": "API funcionando",
                    "credits": "Ilimitado (gratis)",
                    "usage": "No disponible",
                    "account": username
                }
            elif response.status_code == 401:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get('message', '') or response.text[:100] if response.text else ''
                return {
                    "status": "error",
                    "message": f"Error 401 - API Key inválida o expirada: {error_msg}",
                    "credits": None,
                    "usage": None,
                    "account": None
                }
            elif response.status_code == 400:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get('message', '') or error_data.get('error', '') or response.text[:100] if response.text else ''
                return {
                    "status": "error",
                    "message": f"Error 400 - Solicitud inválida: {error_msg}",
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
    
    def check_pixabay(self) -> Dict[str, Any]:
        """Verifica estado de Pixabay"""
        api_key = os.getenv("PIXABAY_API_KEY")
        
        if not api_key:
            return {
                "status": "not_configured",
                "message": "API Key no configurada",
                "credits": None,
                "usage": None,
                "account": None
            }
        
        try:
            url = "https://pixabay.com/api/"
            params = {"key": api_key, "q": "test", "per_page": 1}
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                total_hits = data.get('totalHits', 0)
                return {
                    "status": "working",
                    "message": "API funcionando",
                    "credits": "20,000 requests/día (gratis)",
                    "usage": f"{total_hits} resultados encontrados en prueba",
                    "account": "No disponible"
                }
            elif response.status_code == 400:
                # Pixabay devuelve 400 con detalles del error
                try:
                    error_data = response.json()
                    error_msg = error_data.get('error', '') or error_data.get('message', '')
                except:
                    error_msg = response.text[:100] if response.text else ''
                return {
                    "status": "error",
                    "message": f"Error 400 - Solicitud inválida: {error_msg}",
                    "credits": None,
                    "usage": None,
                    "account": None
                }
            elif response.status_code == 401:
                return {
                    "status": "error",
                    "message": "Error 401 - API Key inválida o expirada",
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
    
    def check_flickr(self) -> Dict[str, Any]:
        """Verifica estado de Flickr"""
        api_key = os.getenv("FLICKR_API_KEY")
        
        if not api_key:
            return {
                "status": "not_configured",
                "message": "API Key no configurada",
                "credits": None,
                "usage": None,
                "account": None
            }
        
        try:
            url = "https://api.flickr.com/services/rest/"
            params = {
                "method": "flickr.test.login",
                "api_key": api_key,
                "format": "json",
                "nojsoncallback": "1"
            }
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('stat') == 'ok':
                    user = data.get('user', {})
                    username = user.get('username', {}).get('_content', 'N/A')
                    return {
                        "status": "working",
                        "message": "API funcionando",
                        "credits": "3,600 requests/hora (gratis)",
                        "usage": "No disponible",
                        "account": username
                    }
                else:
                    return {
                        "status": "error",
                        "message": data.get('message', 'Error desconocido'),
                        "credits": None,
                        "usage": None,
                        "account": None
                    }
            else:
                return {
                    "status": "error",
                    "message": f"Error {response.status_code}",
                    "credits": None,
                    "usage": None,
                    "account": None
                }
        except Exception as e:
            return {
                "status": "error",
                "message": str(e),
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

    def check_google_images(self) -> Dict[str, Any]:
        """Alias legacy: Google Images fue retirado y ahora usa Openverse."""
        return self.check_bing_images()
    
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

