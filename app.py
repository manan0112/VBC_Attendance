
import streamlit as st
import pandas as pd
from dateutil import parser

st.set_page_config(page_title="Attendance Processor", layout="wide")
st.image("VBC_4X.jpeg", width=180)
st.title("Attendance Processor")
st.markdown("""
Upload a UTF-16 tab-delimited ALOG file exported from your biometric device.\
The app will output a per-employee, per-day pivot table with IN - OUT (HH:MM).\
- Only rows with valid Name and EnNo are processed.\
- De-bursting: multiple punches in the same second are collapsed.\
- IN = first DutyOn, OUT = last DutyOff per day.\
- Download the pivot as CSV.\
- See raw parsed data in the expander below.
""")

# Helper to decode file
@st.cache_data(show_spinner=False)
def decode_file(uploaded_file):
	try:
		content = uploaded_file.read()
		text = content.decode('utf-16')
	except UnicodeDecodeError:
		text = content.decode('utf-8')
	return text

def clean_datetime(dt_str):
	if not isinstance(dt_str, str):
		return None
	dt_str = dt_str.split('...')[0].strip()
	try:
		return parser.parse(dt_str)
	except Exception:
		return None

def process_file(uploaded_file):
	text = decode_file(uploaded_file)
	lines = text.splitlines()
	if not lines:
		return None, None, None
	header = lines[0].strip().split('\t')
	data = [l.strip().split('\t') for l in lines[1:] if l.strip()]
	df = pd.DataFrame(data, columns=header)

	# Filter: drop blank Name or EnNo == '00000000'
	df = df[(df['Name'].str.strip() != '') & (df['EnNo'].str.strip() != '00000000')]

	# Clean DateTime
	df['DateTime_clean'] = df['DateTime'].apply(lambda x: x.split('...')[0].strip() if isinstance(x, str) else '')
	df['dt'] = df['DateTime_clean'].apply(clean_datetime)
	df = df.dropna(subset=['dt'])
	df['Date'] = df['dt'].dt.strftime('%Y-%m-%d')
	df['time_s'] = df['dt'].dt.strftime('%H:%M:%S')

	# De-burst: sort, drop duplicates per Name+Date+time_s
	df = df.sort_values('dt')
	df = df.drop_duplicates(subset=['Name', 'Date', 'time_s'], keep='first')

	# Compute IN/OUT based only on time (ignore DutyOn/DutyOff)
	ins = df.groupby(['Name', 'Date'])['dt'].min().reset_index().rename(columns={'dt': 'IN'})
	outs = df.groupby(['Name', 'Date'])['dt'].max().reset_index().rename(columns={'dt': 'OUT'})
	merged = pd.merge(ins, outs, on=['Name', 'Date'], how='outer')
	merged['IN_str'] = merged['IN'].dt.strftime('%H:%M')
	merged['OUT_str'] = merged['OUT'].dt.strftime('%H:%M')
	merged['duration'] = merged.apply(lambda r: (r['OUT'] - r['IN']) if pd.notnull(r['IN']) and pd.notnull(r['OUT']) and r['OUT'] >= r['IN'] else pd.NaT, axis=1)
	merged['duration_str'] = merged['duration'].apply(lambda d: f"{int(d.total_seconds()//3600):02}:{int((d.total_seconds()%3600)//60):02}" if pd.notnull(d) else '')
	# Build a multi-indexed DataFrame: for each date, 3 columns (IN, OUT, Hours)
	reshaped = merged[['Name', 'Date', 'IN_str', 'OUT_str', 'duration_str']].copy()
	reshaped = reshaped.rename(columns={'IN_str': 'IN', 'OUT_str': 'OUT', 'duration_str': 'Hours'})
	reshaped = reshaped.set_index(['Name', 'Date'])
	reshaped = reshaped.unstack('Date')
	# MultiIndex columns: (col, date)
	reshaped.columns = pd.MultiIndex.from_tuples([(date, col) for col, date in reshaped.columns])
	reshaped = reshaped.sort_index(axis=1, level=0)
	reshaped = reshaped.reset_index()
	return df, merged, reshaped

uploaded_file = st.file_uploader("Upload ALOG file (.txt/.tsv)", type=['txt', 'tsv'])
if uploaded_file:
	df, merged, reshaped = process_file(uploaded_file)
	if reshaped is not None:
		# Flatten columns for display and CSV: (date, IN) -> 'date IN'
		display_df = reshaped.copy()
		display_df.columns = [f"{col[0]} {col[1]}" if isinstance(col, tuple) else col for col in display_df.columns]
		st.dataframe(display_df, use_container_width=True, hide_index=True)
		csv = display_df.to_csv(index=False).encode('utf-8')
		st.download_button("Download Table as CSV", csv, "attendance_table.csv", "text/csv")
	with st.expander("Show parsed, filtered, de-bursted rows"):
		if df is not None:
			st.dataframe(df[['Name', 'EnNo', 'In/Out', 'Mode', 'DateTime', 'dt']])
		else:
			st.write("No data parsed.")
else:
	st.info("Please upload a .txt or .tsv ALOG file.")
