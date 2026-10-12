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
