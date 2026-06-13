import os
import requests
from dotenv import load_dotenv
import facebook_uploader

def main():
    print("Obteniendo token de página...")
    try:
        page_token, page_id = facebook_uploader._resolve_page_access_token()
    except Exception as e:
        print(f"Error resolviendo token: {e}")
        return

    test_ids = [
        "800798733094206",
        "1066979239830477",
        "1645974753383924",
        "964551322688608",
        "1686090179485982",
        "1683077519792195"
    ]

    for vid in test_ids:
        print(f"Borrando {vid}...")
        url = facebook_uploader._graph_api_url(vid)
        response = requests.delete(url, params={"access_token": page_token})
        
        if response.status_code == 200:
            print(f" -> Borrado exitosamente: {response.json()}")
        else:
            print(f" -> Error borrando {vid}: HTTP {response.status_code} - {response.text}")

if __name__ == "__main__":
    main()
