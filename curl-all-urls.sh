#!/bin/bash

# Fetch all URLs for Cloud Run services in the project
echo "Fetching Cloud Run URLs..."
URLS=$(gcloud run services list --format="value(status.url)")

if [ -z "$URLS" ]; then
  echo "No Cloud Run services found."
  exit 0
fi

echo "Pinging endpoints..."
echo "------------------------"

# Loop through each URL and curl it
for url in $URLS; do
  echo "Endpoint: $url"
  
  # -s: Silent mode (hides progress bar)
  # -o /dev/null: Discards the response body to keep the terminal clean
  # -w: Prints the specific HTTP status code
  curl -s -o /dev/null -w "Status Code: %{http_code}\n" "$url"
  
  echo "------------------------"
done
