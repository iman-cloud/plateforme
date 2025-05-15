from flask import Flask, request, render_template
import ee
import folium
from datetime import datetime, timedelta
import plotly.graph_objects as go
import os

# Initialiser Earth Engine
project_id = 'suiviminier2025'
ee.Initialize(project=project_id)

# Flask app
app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    # Indice par défaut
    indice = request.form.get('indice', 'NDVI')  # valeur par défaut : NDVI
    band_name = indice

    # Zone d'étude (exemple simple)
    geometry = ee.Geometry.Polygon([
  [
    [-7.055722052035492, 33.74347514551762],
    [-7.055722052035492, 33.720217304441604],
    [-7.025360624366215, 33.720217304441604],
    [-7.025360624366215, 33.74347514551762],
    [-7.055722052035492, 33.74347514551762]
  ]
])

    # Période
    end_date = datetime.today().strftime('%Y-%m-%d')
    start_date = (datetime.today() - timedelta(days=10)).strftime('%Y-%m-%d')

    # Images Sentinel-2
    collection = ee.ImageCollection("COPERNICUS/S2_HARMONIZED") \
        .filterBounds(geometry) \
        .filterDate(start_date, end_date) \
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20)) \
        .sort('system:time_start', False)

    latest_image = collection.first()

    # Calcul de l'indice
    if indice == 'NDVI':
        image_index = latest_image.normalizedDifference(['B8', 'B4']).rename('NDVI')
        vis = {'min': 0.0, 'max': 1.0, 'palette': ['blue', 'white', 'green']}
    elif indice == 'SAVI':
        image_index = latest_image.expression(
            '((NIR - RED) / (NIR + RED + L)) * (1 + L)',
            {
                'NIR': latest_image.select('B8'),
                'RED': latest_image.select('B4'),
                'L': 0.5
            }
        ).rename('SAVI')
        vis = {'min': 0.0, 'max': 1.0, 'palette': ['purple', 'white', 'orange']}
    elif indice == 'NDWI':
        image_index = latest_image.normalizedDifference(['B3', 'B8']).rename('NDWI')
        vis = {'min': -1.0, 'max': 1.0, 'palette': ['brown', 'white', 'blue']}
    else:
        return "Indice non supporté", 400

    # Moyenne actuelle
    mean_dict = image_index.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=geometry,
        scale=10,
        maxPixels=1e9
    ).getInfo()

    mean_value = mean_dict.get(band_name)

    # Carte avec Folium
    center = geometry.centroid().coordinates().getInfo()[::-1]
    m = folium.Map(location=center, zoom_start=10)
    map_id = image_index.getMapId(vis)
    folium.TileLayer(
        tiles=map_id['tile_fetcher'].url_format,
        attr=f'{indice} - GEE',
        overlay=True,
        name=indice
    ).add_to(m)

    map_filename = f"static/carte_{indice.lower()}.html"
    os.makedirs('static', exist_ok=True)
    m.save(map_filename)

    # Historique sur 5 ans
    values = []
    years = []

    for i in range(5, 0, -1):
        year = datetime.today().year - i
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").replace(year=year).strftime("%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d").replace(year=year).strftime("%Y-%m-%d")

            past_collection = ee.ImageCollection("COPERNICUS/S2_HARMONIZED") \
                .filterBounds(geometry) \
                .filterDate(start, end) \
                .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20))

            if past_collection.size().getInfo() == 0:
                values.append(None)
                years.append(str(year))
                continue

            if indice == 'NDVI':
                past_index = past_collection.map(lambda img: img.normalizedDifference(['B8', 'B4']).rename('NDVI'))
            elif indice == 'SAVI':
                def calc_savi(img):
                    return img.expression(
                        '((NIR - RED) / (NIR + RED + L)) * (1 + L)',
                        {
                            'NIR': img.select('B8'),
                            'RED': img.select('B4'),
                            'L': 0.5
                        }
                    ).rename('SAVI')
                past_index = past_collection.map(calc_savi)
            elif indice == 'NDWI':
                past_index = past_collection.map(lambda img: img.normalizedDifference(['B3', 'B8']).rename('NDWI'))

            mean_img = past_index.mean()
            mean_dict = mean_img.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=geometry,
                scale=10,
                maxPixels=1e9
            ).getInfo()

            mean_val = mean_dict.get(band_name)
            values.append(mean_val)
            years.append(str(year))
        except Exception as e:
            values.append(None)
            years.append(str(year))

    # Année actuelle
    years.append(str(datetime.today().year))
    values.append(mean_value)

    # Graphique Plotly
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=years, y=values, mode='lines+markers', name=band_name))
    fig.update_layout(
        title=f'Évolution de {band_name} moyen (5 dernières années + actuel)',
        xaxis_title='Année',
        yaxis_title=f'{band_name} moyen',
        yaxis=dict(range=[-1, 1] if indice == 'NDWI' else [0, 1]),
        template='plotly_white'
    )

    graph_filename = f"static/graphique_{indice.lower()}.html"
    fig.write_html(graph_filename)

    # Explications simples des indices
    explanations = {
        'NDVI': "L'indice NDVI (Normalized Difference Vegetation Index) est utilisé pour surveiller la végétation. Il varie entre -1 et 1. Une valeur proche de 1 indique une forte végétation.",
        'SAVI': "L'indice SAVI (Soil Adjusted Vegetation Index) est similaire au NDVI, mais ajuste l'effet du sol. Il est plus précis dans les zones semi-arides.",
        'NDWI': "L'indice NDWI (Normalized Difference Water Index) est utilisé pour identifier l'eau. Il varie entre -1 et 1. Une valeur proche de 1 indique une grande quantité d'eau."
    }

    # Conclusion basée sur les résultats
    conclusion = ""
    if mean_value > 0.6:
        conclusion = f"La zone présente une végétation dense avec un indice {indice} élevé, ce qui indique une bonne couverture végétale."
    elif mean_value > 0.3:
        conclusion = f"L'indice {indice} montre une végétation modérée dans la zone."
    else:
        conclusion = f"L'indice {indice} est faible, suggérant une faible couverture végétale ou une zone semi-aride."

    return render_template('dashboard.html',
                           map_html=os.path.basename(map_filename),
                           graph_html=os.path.basename(graph_filename),
                           explanation=explanations[indice],
                           conclusion=conclusion,
                           selected_index=indice)


if __name__ == '__main__':
    app.run(debug=True)
