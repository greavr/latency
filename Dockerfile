FROM python:3.11-slim 
WORKDIR /app 
COPY app/ . 
RUN pip install -r requirements.txt 
# Use port 8080 for Cloud Run 
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]