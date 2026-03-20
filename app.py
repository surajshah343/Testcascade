import streamlit as st
import pandas as pd
import plotly.express as px
import io

# set_page_config must be the very first Streamlit command
st.set_page_config(page_title="Cascade Optimizer", layout="wide")
#
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False
    if st.session_state["password_correct"]:
        return True

    st.title("🔒 Access Restricted - Hilco Only")
    try:
        correct_pass = st.secrets["password"]
    except:
        correct_pass = "admin123" 

    with st.form("password_form"):
        password_input = st.text_input("Please enter the access password:", type="password")
        submit_password = st.form_submit_button("Login")
        if submit_password:
            if password_input == correct_pass:
                st.session_state["password_correct"] = True
                st.rerun()
            else:
                st.error("😕 Password incorrect")
    return False

# THIS IS THE MISSING PIECE: Call the function and stop execution if not logged in
if not check_password():
    st.stop()

st.title("🚌 Bus Cascade & Optimization Engine by Suraj Shah")


#st.markdown("""
#**Strategy:** Treat all inventory as a **seperate Pool**. Prioritize the strictest age constraints first and assign the oldest valid vehicles to minimize leases.
#""")

uploaded_file = st.file_uploader("Upload Excel Fleet Data", type=["xlsx", "csv"])

if uploaded_file:
    try:
        if uploaded_file.name.endswith('.csv'):
            st.error("Please upload the original Excel file (.xlsx) containing both Tabs.")
            st.stop()
        else:
            df_a = pd.read_excel(uploaded_file, sheet_name=0) 
            df_b = pd.read_excel(uploaded_file, sheet_name=1)

        # 1. Clean and Prepare Tab A (Requirements)
        mapping = [
            {'Type': 'A', 'MaxAge': 'Max age type A', 'Target': 'Vehicle Count A'},
            {'Type': 'C', 'MaxAge': 'Max age type C', 'Target': 'Vehicle Count C'},
            {'Type': 'VAN', 'MaxAge': 'Max age type VAN', 'Target': 'Vehicle Count Van'}
        ]
        
        req_list = []
        for item in mapping:
            temp = df_a[['Location', 'End Year', item['MaxAge'], item['Target']]].copy()
            temp['Type'] = item['Type']
            temp = temp.rename(columns={item['MaxAge']: 'MaxAge', item['Target']: 'Target', 'End Year': 'EndYear'})
            req_list.append(temp)
        
        reqs = pd.concat(req_list, ignore_index=True)
        reqs['Type'] = reqs['Type'].astype(str).str.upper().str.strip()
        
        # 2. Clean and Prepare Tab B (Global Inventory Pool)
        inv = df_b[['VINs', 'Current Age', 'Type']].copy()
        inv['Type'] = inv['Type'].astype(str).str.upper().str.strip()
        
        start_year = 2026
        max_end_year = int(reqs['EndYear'].max())

        if st.sidebar.button("Run Pool Optimization"):
            
            audit_records = []
            lease_summary = []
            
            # Active Fleet Tracker
            fleet = inv.copy()
            
            progress_bar = st.progress(0)
            
            # 3. Year-by-Year Simulation Loop
            for year in range(start_year, max_end_year + 1):
                if year > start_year:
                    fleet['Current Age'] += 1
                
                available_pool = fleet.copy()
                liquidated_this_year = [] # Track what to remove permanently
                
                for v_type in ['A', 'C', 'VAN']:
                    # Get absolute max age for this type company-wide to determine true "Liquidation"
                    company_max_age = reqs[reqs['Type'] == v_type]['MaxAge'].max()
                    
                    type_pool = available_pool[available_pool['Type'] == v_type].copy()
                    type_pool = type_pool.sort_values('Current Age', ascending=False)
                    
                    active_reqs = reqs[(reqs['Type'] == v_type) & (year <= reqs['EndYear'])].copy()
                    active_reqs = active_reqs.sort_values('MaxAge', ascending=True)
                    
                    for _, req in active_reqs.iterrows():
                        loc = req['Location']
                        target = req['Target']
                        max_age = req['MaxAge']
                        
                        assigned_count = 0
                        
                        # Process Assignments
                        for _ in range(int(target)):
                            valid_vins = type_pool[type_pool['Current Age'] <= max_age]
                            
                            if not valid_vins.empty:
                                chosen_vin_idx = valid_vins.index[0]
                                chosen_vehicle = type_pool.loc[chosen_vin_idx]
                                
                                audit_records.append({
                                    'Calendar_Year': year,
                                    'VINs': chosen_vehicle['VINs'],
                                    'Type': v_type,
                                    'Current Age': chosen_vehicle['Current Age'],
                                    'Assigned_Location': loc,
                                    'Status': 'Assigned'
                                })
                                
                                type_pool = type_pool.drop(chosen_vin_idx)
                                assigned_count += 1
                            else:
                                break
                        
                        # Process Deficits / Leases
                        deficit = int(target) - assigned_count
                        if deficit > 0:
                            # Log leases directly into the audit trail as unique items
                            for i in range(deficit):
                                audit_records.append({
                                    'Calendar_Year': year,
                                    'VINs': f'NEW_LEASE_{loc}_{v_type}_{i+1}',
                                    'Type': v_type,
                                    'Current Age': 0,
                                    'Assigned_Location': loc,
                                    'Status': 'Leased'
                                })
                            
                        lease_summary.append({
                            'Calendar_Year': year,
                            'Location': loc,
                            'Type': v_type,
                            'Target': target,
                            'Assigned_From_Pool': assigned_count,
                            'New_Leases_Required': max(0, deficit),
                            'Units_Liquidated': 0  # Standard location rows have 0 liquidations
                        })

                    # Process Leftovers (Liquidated vs Spare)
                    liquidated_count = 0
                    for _, unassigned in type_pool.iterrows():
                        # If it exceeds the max age of the most lenient location, it is Liquidated
                        is_liquidated = unassigned['Current Age'] > company_max_age
                        
                        if is_liquidated:
                            liquidated_count += 1
                            liquidated_this_year.append(unassigned['VINs'])
                        
                        audit_records.append({
                            'Calendar_Year': year,
                            'VINs': unassigned['VINs'],
                            'Type': v_type,
                            'Current Age': unassigned['Current Age'],
                            'Assigned_Location': 'RETIRED' if is_liquidated else 'GLOBAL POOL',
                            'Status': 'Liquidated' if is_liquidated else 'Spare'
                        })
                    
                    # Add a dedicated row so the Units_Liquidated column populates correctly for the year/type
                    if liquidated_count > 0:
                        lease_summary.append({
                            'Calendar_Year': year,
                            'Location': 'RETIRED POOL',
                            'Type': v_type,
                            'Target': 0,
                            'Assigned_From_Pool': 0,
                            'New_Leases_Required': 0,
                            'Units_Liquidated': liquidated_count
                        })
                        
                # Remove permanently liquidated units from the main fleet so they don't age and reappear next year
                if liquidated_this_year:
                    fleet = fleet[~fleet['VINs'].isin(liquidated_this_year)]
                        
                progress_bar.progress((year - start_year + 1) / (max_end_year - start_year + 1))

            # --- Presentation & Export ---
            audit_df = pd.DataFrame(audit_records)
            lease_df = pd.DataFrame(lease_summary) if lease_summary else pd.DataFrame(columns=['Calendar_Year', 'Location', 'Type', 'Target', 'Assigned_From_Pool', 'New_Leases_Required', 'Units_Liquidated'])

            st.divider()
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Leases Needed (Over Simulation)", lease_df['New_Leases_Required'].sum() if not lease_df.empty else 0)
            c2.metric("Total Vehicles Liquidated", audit_df[audit_df['Status'] == 'Liquidated']['VINs'].nunique())
            c3.metric("Simulation End Year", max_end_year)

            st.subheader("Lease Requirements by Year")
            if not lease_df.empty:
                # FIX 1: Used the correct dataframe variable `yearly_summary`
                yearly_summary = lease_df.groupby('Calendar_Year')[['New_Leases_Required', 'Units_Liquidated']].sum().reset_index()
                # FIX 2: Passed `y` as a list to plot both columns without a syntax error
                fig = px.bar(yearly_summary, x='Calendar_Year', y=['New_Leases_Required', 'Units_Liquidated'], 
                             title="Total Network Deficit (Leases Triggered)")
                st.plotly_chart(fig, use_container_width=True)

            # --- NEW ADDITION: Yearly Summary ---
            #st.subheader("📅 Yearly Summary")
            #if not lease_df.empty:
            #    yearly_summary = lease_df.groupby('Calendar_Year')[['New_Leases_Required', 'Units_Liquidated']].sum().reset_index()
            #    st.dataframe(yearly_summary, use_container_width=True)
            # ------------------------------------

            st.subheader("📋 Lease & Liquidation Log")
            st.dataframe(lease_df.sort_values(['Calendar_Year', 'Location']) if not lease_df.empty else lease_df, use_container_width=True)

            st.subheader("🔍 Pool Allocation Audit")
            search = st.text_input("Filter by VIN, Status (Assigned, Liquidated, Leased), or Location")
            
            display_audit = audit_df.copy()
            if search:
                display_audit = display_audit[display_audit['VINs'].astype(str).str.contains(search, case=False) | 
                                              display_audit['Status'].astype(str).str.contains(search, case=False) |
                                              display_audit['Assigned_Location'].astype(str).str.contains(search, case=False)]
                
            st.dataframe(display_audit, use_container_width=True)

            # Export Excel with Yearly & Type Tabs
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                # Tab 1: High level summary of all leases and liquidations
                lease_df.to_excel(writer, sheet_name='Lease Summary', index=False)
                
                # Sort logically: Assigned -> Leased -> Spare -> Liquidated
                status_order = {'Assigned': 1, 'Leased': 2, 'Spare': 3, 'Liquidated': 4}
                
                # Create a specific tab for EVERY year and EVERY type (A_2025, C_2025, VAN_2025...)
                for out_year in range(start_year, max_end_year + 1):
                    year_df = audit_df[audit_df['Calendar_Year'] == out_year].copy()
                    
                    for v_type in ['A', 'C', 'VAN']:
                        type_year_df = year_df[year_df['Type'] == v_type].copy()
                        
                        if not type_year_df.empty:
                            type_year_df['Order'] = type_year_df['Status'].map(status_order)
                            type_year_df = type_year_df.sort_values(['Order', 'Assigned_Location']).drop(columns=['Order'])
                            
                            # Name the tab A_2025, C_2025, VAN_2025, etc.
                            sheet_name = f"{v_type}_{out_year}"
                            type_year_df.to_excel(writer, sheet_name=sheet_name, index=False)
            
            st.download_button(
                label="📥 Download Full Yearly & Type Audit (Excel)",
                data=output.getvalue(),
                file_name="Yearly_Fleet_Audit_Tabs.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    except Exception as e:
        st.error(f"Execution Error: {e}")
        st.info("Ensure the Excel file contains your original Tab A (Location, End Year, Max Age, etc.) and Tab B (VINs, Current Age, Type).")

else:
    st.info("Upload the Fleet Excel Data.")
