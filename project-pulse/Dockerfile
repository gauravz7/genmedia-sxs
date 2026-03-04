# Stage 1: Build the frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Copy frontend source code
COPY frontend ./
# Strip the URL so the built output relies completely on relative paths mapped to the FastAPI static handler
ENV NEXT_PUBLIC_API_URL=""
RUN npm run build

# Stage 2: Build the backend and run the unified server
FROM python:3.12-slim
WORKDIR /app

# Install python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy python app
COPY backend /app/

# Remove any old static artifacts and mount the fresh compiled NextJS app statically 
RUN rm -rf /app/static
COPY --from=frontend-builder /app/frontend/out /app/static

ENV PORT=8080
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
