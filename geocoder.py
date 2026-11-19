import pandas as pd
from geopy.geocoders import Nominatim, ArcGIS
from geopy.extra.rate_limiter import RateLimiter
from tqdm.notebook import tqdm
tqdm.pandas()

nominatim = Nominatim(user_agent="geoapi")
esri = ArcGIS()

fileName = "listes/LEC-communiquee-HAMBOURG-20240614" 
i = 0

# Don't forget to add a [lat, lng, score] columns

# Load your CSV file
df = pd.read_csv(f"{fileName}.csv")

# Setup geocoder
geolocator = Nominatim(user_agent="my-geocoder-69")
geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1)

# Build the address string
# df["full_address"] = df["Adresse de résidence"] + ", " + df["Code postal"].astype(str) + " " + df["Commune"].astype(str) 
df["full_address"] = df["Adresse de résidence"] + ", " + df["Code postal"].astype(str) 

print(df)

# Apply geocoding
def get_lat_lng_score(row):
    global i
    i += 1
    if not pd.isna(row["lat"]):
        return pd.Series([row["lat"], row["lng"], row["score"]])
    address = row['full_address']
    # First try Nominatim
    try:
        location = nominatim.geocode(address, addressdetails=True, timeout=10)
    except Exception as e:
        print(f"Nominatim error for '{address}': {e}")
        location = None

    # If Nominatim fails, try ArcGIS (ESRI)
    if not location:
        try:
            location = esri.geocode(address, timeout=10)
        except Exception as e:
            print(f"ESRI error for '{address}': {e}")
            location = None
    
    if location:
        lat = location.latitude
        lng = location.longitude
        score = location.raw.get("importance", None)
        print([address, lat, lng, score])
        return pd.Series([lat, lng, score])
    else:
        print("Adress not found : {}".format(address))
        return pd.Series([None, None, None])

df[["lat", "lng", "score"]] = df.apply(get_lat_lng_score, axis=1)

# Save result
df.to_csv(f"{fileName}_geocoded_data.csv", index=False)