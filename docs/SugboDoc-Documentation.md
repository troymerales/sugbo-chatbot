# SugboDoc — User Documentation

*"SugboDoc — better healthcare together."*

SugboDoc is a cloud-based clinic and practice management platform for healthcare
providers. It covers the full patient journey — scheduling, registration,
clinical encounters and documentation, immunizations, billing and payments — plus
the administrative setup behind it: staff accounts, departments, resources,
locations, document templates, and subscriptions.

This guide is organized by module. Most day-to-day clinical work happens inside a
**patient record**, which is made up of *cards* (Appointments, Encounters, Vital
Signs, SOAP Notes, Diagnosis, Clinical Notes, Prescriptions, Service Requests,
Uploaded Files, Immunizations, Bills & Payment). Administrative work happens in
dedicated sidebar modules.

> This documentation was reconstructed from the [SugboDoc full tutorial video](https://www.youtube.com/watch?v=c2WEOZnOhps).
> Chapter timestamps are cited as `[mm:ss]` for reference. A few chapter titles in
> the source were mislabeled; the corrected topic is used here and noted where
> relevant.

---



## Table of contents

1. [Core concepts](#core-concepts)
2. [Schedule module](#schedule-module)
3. [Patients (Patient Worklist)](#patients-patient-worklist)
4. [Appointments](#appointments)
5. [Encounters (Patient Visits)](#encounters-patient-visits)
6. [Vital Signs](#vital-signs)
7. [SOAP Notes](#soap-notes)
8. [Diagnosis](#diagnosis)
9. [Clinical Notes](#clinical-notes)
10. [Clinical Notes Templates](#clinical-notes-templates)
11. [Prescriptions](#prescriptions)
12. [Service Requests](#service-requests)
13. [Uploaded Files](#uploaded-files)
14. [Immunizations](#immunizations)
15. [Bills & Payment (patient record)](#bills--payment-patient-record)
16. [Charges (Bills & Payments setup)](#charges-bills--payments-setup)
17. [Staff Management](#staff-management)
18. [Departments](#departments)
19. [Resources](#resources)
20. [Locations (Branches)](#locations-branches)
21. [Facility Settings — Document Templates](#facility-settings--document-templates)
22. [Subscriptions](#subscriptions)

---



## Core concepts


| Term                                   | Meaning                                                                                                                                                           |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Patient Worklist**                   | Your list of patients. Entry point to every patient record.                                                                                                       |
| **Patient record**                     | A patient's profile, containing all clinical and billing *cards*.                                                                                                 |
| **Card**                               | A section within the patient record (e.g. Vital Signs card, Diagnosis card). Each card has an **Add** button and a **View all** option.                           |
| **Encounter / Patient Visit**          | A single episode of care. Most clinical entries (SOAP notes, diagnosis, prescriptions, immunizations, invoices, etc.) are *linked to an encounter*.               |
| **Healthcare provider / Practitioner** | The doctor or nurse delivering care.                                                                                                                              |
| **Location / Branch**                  | A clinic or facility site. Can be **internal** (your own consultation sites) or **external** (sites where practitioners are only affiliated — rounds, surgeries). |
| **Grayed-out fields**                  | On edit screens, only non-grayed fields can be changed.                                                                                                           |
| **Short codes**                        | Template variables (e.g. patient full name, age, address, diagnosis) that auto-fill with patient data when a document is generated.                               |
| **Export (A4 / A5)**                   | Clinical documents (prescriptions, service requests, certificates) can be printed or downloaded as PDF in A4 or A5 paper size.                                    |


**General editing pattern (applies to most cards):**

1. Open the patient record from the Patient Worklist.
2. Locate the card → **View all**.
3. Select the item → **three dots** (or arrow) → **Edit** / **View** / **Void**.
4. Change the allowed fields → review → **Submit** / **Update** / **Save**.

---



## Schedule module

*Chapter: Add Schedule [00:11]*

Defines a practitioner's recurring availability so appointments can be booked
against real time slots.

**Create a schedule**

1. Sidebar → **Schedule** → **All Schedule**.
2. Click **Add new** → the *Add Schedule* modal opens.
3. Set the fields:
  - **Location** — where the schedule applies.
  - **Healthcare provider** — who the schedule is assigned to.
  - **Appointment duration** — length of each slot.
  - **Days available** — select the weekdays (e.g. Monday, Wednesday, Friday).
  - **Time slots** — click the **+** on the right to add a slot and set its
  start/end time. Multiple time slots per day are allowed.
4. Review the added schedule for accuracy.
5. Click **Add** to save.

---



## Patients (Patient Worklist)

*Chapter: Adding of Patient [01:24]*

The Patient Worklist is your roster of patients. New patients are added either by
creating a fresh profile or by linking an existing SugboDoc account.

### Add a new patient

1. Sidebar → **Patient Worklist** → **Add patient**.
2. Choose **Add new patient**.
3. Fill in the patient's details:
  - Personal information
  - Contact information
  - Address (if applicable)
  - **Related person** (optional): relationship to patient, personal
  information, address — then click **Add** for that person.
  - Profile photo (optional).
4. Click **Add**. A confirmation message confirms the patient was created.



### Add a patient via search

Use this only when the patient **already has a SugboDoc account** but is not yet
on your list.

1. **Add patient** → **Via search**.
2. Choose a search method:
  - **Patient number** — enter the patient's SugboDoc number, first name, and
   last name.
  - **Patient details** — search by identifying details.
3. Click **Search**.
4. In the results, find the correct patient → **Add patient**.
5. A confirmation message confirms they were added to your list.

---



## Appointments

Located on the **Appointment card** inside the patient record.

### Create an appointment

*Chapter: Appointment Creation [03:11]*

1. Open the patient record → **Appointment card** → **Add**.
2. Fill in the details:
  - **Healthcare provider**
  - **Location**
  - **Appointment service**
  - **Appointment date** and **preferred slot**
  - **Appointment status**:
    - **Pending** — patient is still unsure.
    - **Booked** — patient has confirmed.
  - **Reason for visit**
3. Review → **Submit**.



### Update an appointment

*Chapter: Update Appointment [04:26]*

1. Patient record → **Appointment card** → **View all**.
2. Select the appointment → **Edit**.
3. Editable fields only (non-grayed): **service, date, available slots,
  appointment status, reason for visit**.
4. Review → **Submit**.

---



## Encounters (Patient Visits)

An encounter represents one visit/episode of care. Located on the **Encounter
card**.

### Create an encounter

*Chapter: Encounter Creation [05:23]*

1. Sidebar → **Patient Worklist** → open the patient profile.
2. **Encounter card** → **Add encounter**.
3. Select an **encounter type** (pop-up modal).
4. Enter the encounter details:
  - **Encounter status** — e.g. *Patient is receiving care*.
  - **Encounter source** — optional (may be left blank).
  - **Encounter location** — which clinic serves as the location.
  - **Reason for visit**.
5. Click **Submit**.



### Update / end an encounter

*Chapter: Update Encounter [06:28]*

1. Patient record → **Encounter card** → **View all encounters**.
2. Choose the encounter → **three dots** → **Edit encounter**.
3. Change the **encounter status** to reflect the situation — e.g. *Encounter
  completed and patient departed* to end it.
4. Click **Submit**.

---



## Vital Signs

Located on the **Vital Signs card**.

### Add vital signs

*Chapter: Add Vital Signs [07:14]*

1. Patient Worklist → open the patient profile.
2. **Vital Signs card** → **Add vitals**.
3. Optionally link an **encounter**.
4. Enter the measured values: **height, weight, blood pressure, temperature,
  respiration level** (and other available fields).
5. Add **notes** about the patient's condition or the readings (optional).
6. Click **Submit**.



### Edit vital signs

*Chapter: Edit Vital Signs [08:09]*

1. Patient record → **Vital Signs card** → **View all vital signs**.
2. Choose the record → **three dots** → **Edit**.
3. Add or update any values (e.g. add **SPO2**) and update the **notes**.
4. Review → **Submit**.

---



## SOAP Notes

Structured clinical notes: **S**ubjective, **O**bjective, **A**ssessment,
**P**lan. Located on the **SOAP Notes card**.

### Create SOAP notes

*Chapter: SOAP Notes Creation [09:05]*

1. On the patient record, find the **SOAP Notes card** → **Add SOAP notes**.
2. Choose the **encounter** to link the notes to.
3. Enter the **Subjective, Objective, Assessment, and Plan** sections.
4. Optionally tick the checkbox to allow **other care team members** to view the
  notes.
5. Click **Submit**. The notes appear in the patient's record.



### Edit SOAP notes

*Chapter: Edit SOAP Notes [10:06]*

1. Patient record → **SOAP Notes card** → **View all SOAP notes**.
2. Choose the notes → **arrow down** → **Edit**.
3. Editable fields only (non-grayed): **title** and the **SOAP notes** fields.
  You can also **add images** to a section (e.g. add an image to *Objective*,
   add detail to *Plan*).
4. Review → **Submit**.

---



## Diagnosis

Located on the **Diagnosis card / section**.

### Create a diagnosis

*Chapter: Diagnosis Creation [11:08]*

1. Patient Worklist → open the patient profile.
2. **Diagnosis section** → **Add diagnosis**.
3. Choose the **encounter** to link the diagnosis to.
4. Enter:
  - **Diagnosis**
  - **Diagnosis rank**
  - **Diagnosis date**
  - **Diagnosis note** (if applicable)
5. Review → **Submit**.
6. View the entry any time with the **Details** button.



### Edit a diagnosis

*Chapter: Edit Diagnosis [12:07]*

1. Patient record → **Diagnosis card** → **View all diagnosis**.
2. Choose the diagnosis → **three dots** → **Edit**.
3. Click **See more** to expand all fields. Editable fields (non-grayed):
  **onset date, diagnosis rank, diagnosis date, clinical status, verification
   status, diagnosis note**.
4. Review → **Submit**.

---



## Clinical Notes

Free-form, template-driven clinical documentation. Located on the **Clinical
Notes card**. Templates are managed separately (see
[Clinical Notes Templates](#clinical-notes-templates)).

### Create clinical notes

*Chapter: Clinical Notes Creation [13:12]*

1. Open the patient record → **Clinical Notes card** → **Add clinical notes**.
2. Set up the note:
  - **Encounter** to link to.
  - **Template** — select a previously created template.
  - **Attending doctor**.
  - **Category** — selecting one pre-fills the **title** (the title can still be
  changed).
3. Because a template is selected, the **details auto-populate** and **short
  codes** fill in with the patient's data.
4. Add or modify information in the **Clinical Notes details** section as needed.
5. **Show patient banner** / **Show title** toggles — adjust from their defaults
  (e.g. turn **Show patient banner** off).
6. Review → **Submit**.



### Edit clinical notes

*Chapter: Edit Clinical Notes [14:28]*

1. Patient record → **Clinical Notes card**. Either:
  - Click **Edit** directly, or
  - **View all clinical notes** → select the note → **three dots** → **Edit**.
2. Editable fields only (non-grayed): **template, category, title, details**.
3. You can also change the **Show patient banner** and **Show title** toggles.
4. Review → **Submit**.

---



## Clinical Notes Templates

*Chapter: (labeled "Clinical Notes Creation") [15:31]*

Reusable templates that speed up clinical note creation by embedding **short
codes** — variables that auto-fill with patient data.

**Create a template**

1. Sidebar → **Clinical Notes** → **Clinical Notes Templates**.
2. Click **Add template**.
3. Enter a **title** for the template.
4. Set the **Show patient banner** / **Show title** toggles to control what
  appears on notes generated from this template (e.g. toggle **Show title** on).
5. In the template creation area, build the body using **short codes** — e.g.
  short codes for the patient's **full name, age, address, and diagnosis** — so
   these details are filled automatically instead of typed manually.
6. Click **Submit** to save the template.

---



## Prescriptions

Located on the **Prescription card**.

### Create a prescription

*Chapter: Prescription Creation [16:45]*

1. Patient Worklist → open the patient profile.
2. **Prescription card** → **Add prescription**.
3. Select the **attending doctor** and the **encounter** to link to.
4. **Add medication** → **Add medicine**:
  - Search and select a medication from the list.
  - Specify **SIG** (directions), **uses**, and **quantity**.
  - Click **Add**.
5. **If the medication is not listed** → **Create new medication**:
  - Enter **generic name, brand name, dosage, strength, form, uses, side
   effects**.
  - Click **Create**, then add the newly created medicine (found under the
  **Custom** category) with its SIG and quantity → **Add**.
6. Optionally tick the checkbox to **schedule the patient's next appointment** and
  pick the date.
7. Add **additional notes** if needed.
8. Click **Submit** → review the medication list → **Confirm and submit**.



### View / export a prescription

*Chapter: (labeled "Diagnosis Creation") [18:19]*

1. Patient record → **Prescription card**. Either **Details**, or **View all
  prescriptions** → select → **three dots** → **View**.
2. In the modal, click **View prescription** (upper-right). A full prescription
  page opens.
3. **Export**: **Print** or **Download**, choosing paper size **A4** or **A5**.
  Selecting a size with the **PDF** option renders the prescription in that size;
   downloads are saved in the selected size.

---



## Service Requests

Orders for services/procedures to be rendered. Located on the **Service Request
card**.

### Create a service request

*Chapter: Service Requests Creation [19:31]*

1. Patient Worklist → open the patient profile.
2. **Service Request card** → **Add service request**.
3. Select the **encounter** to link to.
4. **Add new service**:
  - Optionally tick the checkbox to specify the **renderer** — **department,
   facility, or practitioner** that should handle the order.
  - Search and select a **service** from the list.
  - Specify the **instruction**.
  - Click **Add**.
5. **If the service is not listed** → **Create new service**:
  - Select a **category**, enter the **service name** → **Add to service list**.
  - Search for the new (custom) service, select it, specify the instruction →
  **Add**.
6. You can **view**, **edit**, or **remove** each added service before submitting.
7. Review → **Submit**.



### Edit a service request

*Chapter: Edit Service Request [21:13]*

1. Patient record → **Service Request card** → **View all service requests**.
2. Choose the request → **three dots** → **Edit**.
3. You can **update a service's details**, **add a new service**, or **remove a
  service**.
4. Review → **Submit**.



### View / export a service request

*Chapter: View Service Request [22:31]*

1. Patient record → **Service Request card** → **View all service requests**.
2. Select the request → **three dots** → **View**. A full details page opens.
3. **Export**: **Print** or **Download**, paper size **A4** or **A5** (PDF renders
  and downloads in the selected size).

---



## Uploaded Files

*Chapter: Upload Files [23:33]*

Attach images or PDFs to a patient's record. Located on the **Uploaded Files
card**.

1. Patient record → **Uploaded Files card** → **Add**.
2. Optionally associate the file with an **encounter**.
3. Choose a **category** for the file.
4. Enter a **title** and **description**.
5. Upload the file(s):
  - Image or PDF.
  - Up to **5 files**, of mixed types.
6. Click **Add file** to complete.

---



## Immunizations

Located on the **Immunization card**. Two record types:


| Type                      | Use when                                                                                                                                         |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Internal immunization** | The current practitioner **administers the vaccine and creates the record**.                                                                     |
| **External immunization** | The vaccine was administered by **another practitioner and not recorded by them**; the current practitioner records it to keep history complete. |




### Add an internal immunization

*Chapter: Add Internal Immunization [24:34]*

1. Patient record → **Immunization card** → **Add** → **Add internal
  immunization**.
2. Select the **encounter** to link to.
3. **Add vaccine** → search for and select the vaccine → **Next**.
4. Fill in: **dosage, lot number, expiration date, date & time administered,
  site, route, vaccination site, reaction**. Add **images** if applicable.
5. Click **Add** to record the vaccine. Add more vaccines if needed.
6. Click **Submit** → review the **immunization preview** → **Confirm and
  submit**.



### Add an external immunization

*Chapter: Add External Immunization [26:31]*

1. Patient record → **Immunization card** → **Add** → **Add external
  immunization**.
2. Search for and select the vaccine → **Next**.
3. On the *Add vaccine* screen:
  - Optionally tick the box if there is **proof** of the external immunization
   (baby's book, vaccination certificate, etc.).
  - Enter the **name of the practitioner** who previously vaccinated the patient.
  - Select the **facility** where it took place.
4. Fill in: **dosage, lot number, expiration date, date & time administered,
  site, route, reaction**.
5. Add an **image as proof** of the previous vaccination.
6. Click **Add** to record the immunization.



### View / export immunizations

*Chapter: View Immunization [28:26]*

1. Patient record → **Immunization card** → **View all**.
2. The **form view** shows by default. Use the top-left toggle to switch to
  **list view** (more organized).
3. List view tabs:
  - **All vaccine** — every vaccine given to the patient (internal or external).
  - **By encounter** — vaccines grouped by encounter.
  - **Created by me** — vaccines administered by the currently logged-in user.
4. **Certificate**: click **Certificate** → **Print** or **Download**, paper size
  **A4** or **A5** (PDF formats to the selected size).

---



## Bills & Payment (patient record)

Located on the **Bills and Payment card**. Handles invoices, charges, deposits,
and voids for a specific patient.

### Create an invoice — patient pays upfront (Paid)

*Chapter: Invoice Creation (Paid) [30:07]*

1. Patient record → **Bills and Payment** section → **Add invoice**.
2. Select the **encounter** to link to.
3. Choose the **invoice due type**.
4. Upper-right → **Add charge**. Choose a charge type:
  - **Co-pay** — two or more parties contribute to the charge.
  - **Self-pay** — the patient covers the charge alone.
  - **Insurance** — covered by the patient's insurance provider.
5. Select **Self-pay**, pick a charge from the list → **Add**.
6. Enter the **payment amount** the patient pays upfront (add a **note** if
  needed). The **total amount** updates to reflect what remains (e.g. reads `0`
   when fully paid).
7. Click **Submit** → on the review prompt, **Continue** to finalize.



### Create an invoice — bill for later (Unpaid)

*Chapter: Invoice Creation (Unpaid) [31:39]*

1. Patient record → **Bills and Payment card** → **Add**.
2. Select the **encounter** to link to.
3. Update the **invoice date** or leave as is.
4. Select the **invoice due type** to define the due date (e.g. *Due on
  receipt*).
5. Upper-right → **Add charge** → select charges based on services rendered
  (e.g. *Face-to-face consultation fee*). Add more as needed → **Add**.
6. On the **item summary**:
  - Adjust **quantities** if necessary.
  - Click the **See more** icon on a charge to view **tax, practitioner/facility
  charge, convenience fee**.
  - Add **discounts** or **promo codes** if applicable.
7. Review → **Submit**.



### Add a deposit to an unpaid invoice

*Chapter: Add Deposit [33:08]*

1. Patient record → **Bills and Payment card** → **View all**.
2. Locate the **Unpaid invoices** card → **Deposit** button (right side).
3. In the prompt, click the **down arrow** next to the invoice to see details.
4. Click **Deposit** → select **Personal**.
5. Enter the **amount** to be paid (match the intended deposit amount).
6. Click **Confirm deposit**. A modal confirms the deposit.



### Void a payment

*Chapter: Void Payment [34:05]*

1. Patient record → **Bills and Payment card** → **View all**.
2. Upper-right → **View all deposit**.
3. Identify the deposit → **down arrow** for details.
4. **Three dots** next to the deposit → options **View** and **Void**.
  - **View** shows the deposit details.
  - **Void** opens a confirmation prompt → click **Void** to finalize.

---



## Charges (Bills & Payments setup)

*Chapter: Charge Creation [35:04]*

Defines the reusable fees that can be added to invoices. Managed under the global
**Bills and Payments** module (not the patient record).

1. Sidebar → **Bills and Payments** → **List of charge groups**.
2. Click **Add charge**.
3. Enter the **charge name** and **description**.
4. Choose a **price type**:
  - **Fixed amount** — a set fee that stays constant for a service.
  - **Variable amount** — a fee that varies with services provided. Further
  classified as **fixed limit** or **percentage limit**.
5. For a fixed amount, input the **amount** to charge the patient.
6. Select the **category**.
7. Choose the **charge type**.
8. Optionally select a **practitioner** the charge applies to.
9. Choose whether the charge is **bookable** or not.
10. Save.

---



## Staff Management

*Chapters: Clerk Account Creation [36:16], Nurse Account Creation [37:02]*

Sidebar → **Staff Management**, then the relevant staff category.

### Add a clerk

1. **Staff Management** → **Clerk** → **Add clerk**.
2. Enter personal details: **name, contact details, address**. Add a **profile
  photo** (optional).
3. Click **Submit**. A confirmation message appears.
4. The clerk receives an **email with login credentials and a temporary
  password**.



### Add a nurse

1. **Staff Management** → **Nurse** → **Add nurse**.
2. Enter personal details: **name, contact details, address, birthday, license
  number**.
3. Indicate whether the nurse is **bookable**.
4. Enter the **consultation fees**. Add a **profile photo** (optional).
5. Click **Submit**. A confirmation message appears.
6. A **verification process** is required before the nurse can fully use the
  account.

---



## Departments

*Chapter: (labeled "Edit Diagnosis") — Add Department [37:56]*

Sidebar → **Department** → **Add department**. Two ways to add:

### From the list

1. Browse the available list and select a department.
2. Modify the **description** if needed.
3. Click **Use** to add it.



### Create a new department

1. Click **Create department**.
2. In the modal, enter the **department name** → **Confirm**.
3. The new department appears at the top of the list under **Previously created
  department**.
4. Click it to add a **description** → **Confirm**.

---



## Resources

*Chapters: Add Resource Classification [39:04], Edit Resource Classification
[40:08], Add Resource Type [41:08], Add Resource [42:37], Edit Resource [43:58]*

Sidebar → **Resource**. The module has two options: **Management** and
**Appointment**. Resource setup is done under **Management**.

**Hierarchy:** Classification → Resource type → Resource.

### Add a resource classification

1. **Resource** → **Management** → **Add classification**.
2. In the *Add resource classification* off-canvas:
  - **Enable pricing** toggle — turn on to activate pricing for the resource
   types under this classification.
  - **Classification name**.
  - **Description**.
3. Review → **Save**.



### Edit a resource classification

1. **Resource management** screen → click the classification (shows its
  **inclusions**).
2. **Edit** (right side) → *Edit resource classification* off-canvas.
3. All fields are editable (e.g. update the **icon** and **description**).
4. Review → **Save**.



### Add a resource type

1. **Resource management** → click the classification to show its inclusions.
2. **Add resource type** → modal opens.
3. Tag the resource type:
  - **To use** — resources with a short time duration (e.g. dialysis machine).
  - **To occupy** — resources billed at a daily rate (e.g. beds).
4. Enter the **resource type name**.
5. **Price per category** — choose **daily**, **distance**, or **usage**.
6. Input the **pricing details**.
7. Add a **resource type description**.
8. Review → **Save**.



### Add a resource

1. **Resource management** → click the classification to show inclusions.
2. Find the target resource type → **three dots** → **Add resource** →
  off-canvas opens.
3. Fill in:
  - **Resource name**
  - **Department** and **Location**
  - **Apply prices from resource type** checkbox — check to inherit the resource
  type's pricing; leave unchecked to enter pricing manually.
  - **Resource description**
  - **Make this resource a location** checkbox — check to designate the resource
  as a location.
4. Review → **Save**.



### Edit a resource

1. **Resource management** → click the classification to show inclusions.
2. Expand the resource type (**drop-down icon**) to list its resources.
3. Find the resource → **three dots** → **Edit** → off-canvas opens.
4. All fields are editable **except the resource type** (e.g. update **resource
  number**, **pricing**, **description**).
5. Review → **Save**.

---



## Locations (Branches)

*Chapters: Add Internal Location [45:08], Add External Location [46:31], Update
Location Details [47:41]*

Sidebar → **Location**. Options: **All** and **Branches**. Branch setup is under
**Branches**, which has two tabs:


| Tab          | Meaning                                                                                     |
| ------------ | ------------------------------------------------------------------------------------------- |
| **Internal** | Your other locations where consultations or facility operations take place.                 |
| **External** | Locations where practitioners are only affiliated for other activities (rounds, surgeries). |




### Add an internal location

1. **Location** → **Branches** → **Internal** tab.
2. Click **Add new** → *Add new internal location* modal.
3. Fill in: **display name, phone number, street address, country, state,
  province, city, municipality, postal code**.
4. Review → **Add**.



### Add an external location

1. **Location** → **Branches** → **External** tab.
2. Click **Add new external location** → modal opens.
3. Fill in the same fields: **display name, phone number, street address,
  country, state, province, city, municipality, postal code**.
4. Review → **Add**.



### Update location details

1. **Location** → **Branches** → select the tab (e.g. Internal).
2. Find the location → **three dots** → **Edit** → modal opens.
3. All fields are editable (e.g. update **display name**, add a **phone
  number**).
4. Review → **Update**.

---



## Facility Settings — Document Templates

*Chapters: Practitioner Header [48:44], Facility Header [50:01]*

Sidebar → **Facility Settings** → **Document Templates**. Configures the header
shown on generated documents (per practitioner).

**Common steps**

1. **Facility Settings** → **Document Templates**.
2. Select a **practitioner** from the drop-down.
3. Choose the **record** to configure — selecting *any record* auto-populates all
  available records.
4. Choose which **header display** to configure: **Practitioner header** or
  **Facility header**.



### Practitioner header

- **Custom hours** toggle — turn on to set specific availability and indicate the
schedule.
- **Auto add signature** toggle — turn on to include the e-signature
automatically.
- Upload a **logo**.
- Input the **S2 license number** (if applicable).
- Use **Preview record** on the sample record to check the result.



### Facility header

- **Auto add signature** toggle — turn on to display the e-signature.
- Upload a **logo**.
- **Show S2** toggle — off by default; turn on to display the S2 license and
input details.
- **Show PTR** toggle — off by default; turn on to show PTR details.
- Review on the **Preview** screen.

---



## Subscriptions

*Chapters: Subscriptions — Payment [51:19], Subscriptions — Add on [52:14]*

Sidebar → **Subscription**.

### Pay the monthly subscription

1. **Subscription** module → **Prepaid** button.
2. In the *Prepaid* modal, choose **existing payment method** or **another
  payment method** (existing is used here for convenience).
3. If the package has previously added add-ons, a confirmation asks whether to
  **include the add-ons** in this payment.
4. Click **Proceed** to finalize. The monthly subscription is paid, keeping
  access to subscription services and included add-ons.



### Add more services / add-ons

1. **Subscription** module → **Get more services**.
2. Browse available services and add-ons (e.g. **staff**, **imaging studies
  storage**, **branches**).
3. **Add more staff**: on the **Staff** card → **See packages** → in the *Add
  staff* modal, adjust the **quantity** (e.g. **+** to add two doctors) →
   **Add**.
4. **Add more branches**: on the **Add branches** card → **See packages** →
  adjust the **quantity** → **Add**.
5. Scroll to the bottom → **Checkout**.
6. On the checkout screen, review the add-ons, quantities, and total.
7. Choose an **existing** or **new payment method** → **Pay**.

---

*End of documentation.*