import time
import argparse
from datetime import datetime
import os
import sys

# Import local x_uploader
try:
    import x_uploader
except ImportError:
    print("Error: No se encontró x_uploader.py. Asegúrate de que esté en la misma carpeta.")
    sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Programador Manual de Posts para X en el VPS")
    parser.add_argument("--fecha", type=str, required=True, help="Fecha y hora de publicación. Formato: 'YYYY-MM-DD HH:MM'")
    parser.add_argument("--texto", type=str, required=True, help="El texto del Tweet")
    parser.add_argument("--imagen", type=str, required=False, default=None, help="Ruta de la imagen a subir (Opcional)")
    
    args = parser.parse_args()
    
    try:
        target_time = datetime.strptime(args.fecha, "%Y-%m-%d %H:%M")
    except ValueError:
        print("Error: Formato de fecha inválido. Usa 'YYYY-MM-DD HH:MM'. Ejemplo: '2026-07-21 14:30'")
        sys.exit(1)
        
    now = datetime.now()
    wait_seconds = (target_time - now).total_seconds()
    
    if wait_seconds <= 0:
        print(f"La fecha programada ({args.fecha}) ya pasó. Publicando inmediatamente...")
        wait_seconds = 0
    else:
        print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Post programado para el {args.fecha}.")
        print(f"El script se dormirá por {wait_seconds:.0f} segundos. ¡Puedes cerrar la sesión si corriste el script con 'nohup' o 'screen'!")
        time.sleep(wait_seconds)
        
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ¡Es la hora! Iniciando publicación...")
    
    media_id = None
    if args.imagen:
        if not os.path.exists(args.imagen):
            print(f"Error: No se encontró la imagen en la ruta {args.imagen}")
            sys.exit(1)
        print("Subiendo imagen a X...")
        media_id = x_uploader.upload_image_to_x(args.imagen)
        if not media_id:
            print("Fallo crítico: No se pudo subir la imagen.")
            sys.exit(1)
            
    print("Publicando el Tweet...")
    success = x_uploader.post_tweet(args.texto, media_id=media_id)
    if success:
        print("¡Tweet programado publicado exitosamente!")
    else:
        print("Error al publicar el Tweet.")

if __name__ == "__main__":
    main()
