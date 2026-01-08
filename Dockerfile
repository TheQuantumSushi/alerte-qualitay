# Base image for Python
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application files into the container
COPY . .

# (Optional) expose a port if you add a healthcheck or web server later
EXPOSE 8080

# Command to run the bot
CMD ["python", "qualitay.py"]
