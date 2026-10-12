# API de conversión DICOM a PNG

## Estructura

```text
.
├── main.py
├── app/
│   ├── api/routes/convert.py
│   ├── core/{config,errors,security}.py
│   ├── services/{batch_converter,dicom_converter}.py
│   └── utils/files.py
├── requirements.txt
└── tests/test_security.py
```

## Ejecutar

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000
```

`POST /api/v1/convert` acepta multipart/form-data con el campo `file` y responde con `image/png`. El límite predeterminado es 15 MiB. Los orígenes CORS se configuran con `CORS_ORIGINS`, separados por comas; si se omite, solo se permiten los localhost de desarrollo declarados en `app/core/config.py`.

La carga se copia por bloques a un archivo temporal privado con nombre aleatorio, se valida el marcador DICOM Part 10 y se elimina en todos los casos. La matriz de píxeles se limita por tamaño antes de decodificar; se aplica la LUT de modalidad y la ventana VOI DICOM cuando existen. Si no hay ventana, se usa un auto-contraste entre los percentiles 1 y 99. Los metadatos se descartan y el PNG se genera sin metadatos. Las muestras de hasta 8 bits se escriben como PNG de 8 bits y las de 9 a 16 bits como PNG de 16 bits. La codificación PNG no agrega pérdida, pero el ajuste de visualización transforma los valores tonales originales.

La interfaz en `/` y `POST /api/v1/convert/batch` aceptan hasta 500 archivos DICOM en el campo multipart `files`. La ruta batch procesa un archivo a la vez y devuelve `imagenes_convertidas.zip` con entradas genéricas (`imagen_001.png`, etc.). Cada archivo puede ocupar hasta 15 MiB; el lote y el ZIP resultante están limitados a 512 MiB. Los archivos multipart se vuelcan a disco a partir de 64 KiB para evitar retener lotes grandes en RAM. Se incluyen plugins pydicom para JPEG, JPEG-LS, JPEG 2000 y RLE.

## Docker

```bash
cp .env.example .env
# Pega en CLOUDFLARE_TUNNEL_TOKEN el token generado por Cloudflare Zero Trust.
docker compose up -d --build
```

En Cloudflare Zero Trust crea un túnel de tipo **Cloudflared/Docker**, copia su token en `.env` y agrega una ruta de hostname público. Configura el servicio de origen de esa ruta como `http://dicom-api:8000`. No publiques el puerto 8000 en el host: el servicio `cloudflared` llega a la API por la red privada de Compose. La interfaz y la API comparten origen, así que `CORS_ORIGINS` puede quedarse vacío.

La imagen de la API corre como usuario no root y usa un worker para mantener acotado el uso de RAM. Reserva al menos 1 GiB de espacio temporal para lotes grandes: durante una conversión pueden coexistir las cargas multipart y el ZIP generado. El volumen `dicom-tmp` es almacenamiento Docker en disco, no `tmpfs`. La configuración disponible está en `.env.example`; los valores de tamaño se expresan en bytes. El archivo `.env` real está excluido de Git y contiene el secreto del túnel: no lo compartas ni lo subas al repositorio.
